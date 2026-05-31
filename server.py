import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


APP_SLUG = "purchase-order-field-extractor"
APP_KEY = "purchase_order_field_extractor"
TOOL_NAME = "purchase_order_field_extractor"
SERVER_NAME = "purchase-order-field-extractor"
BASE_DIR = Path(__file__).resolve().parent

ANNOTATIONS = {
    "readOnlyHint": True,
    "openWorldHint": False,
    "destructiveHint": False,
}

INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "purchase_order_text": {
            "type": "string",
            "description": "Raw purchase order text provided by the user.",
        }
    },
    "required": ["purchase_order_text"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "error"]},
        "purchase_order_number": {"type": ["string", "null"]},
        "supplier_name": {"type": ["string", "null"]},
        "buyer_name": {"type": ["string", "null"]},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_name": {"type": ["string", "null"]},
                    "sku": {"type": ["string", "null"]},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "line_total": {"type": ["number", "null"]},
                },
                "required": [
                    "item_name",
                    "sku",
                    "quantity",
                    "unit_price",
                    "line_total",
                ],
                "additionalProperties": False,
            },
        },
        "currency": {"type": ["string", "null"]},
        "requested_delivery_date": {"type": ["string", "null"]},
        "shipping_address": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "source_text": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "error_type": {
                        "type": "string",
                        "enum": [
                            "missing_field",
                            "invalid_value",
                            "out_of_scope",
                            "internal_error",
                        ],
                    },
                    "message": {"type": "string"},
                },
                "required": ["error_type", "message"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "status",
        "purchase_order_number",
        "supplier_name",
        "buyer_name",
        "items",
        "currency",
        "requested_delivery_date",
        "shipping_address",
        "notes",
        "missing_fields",
        "source_text",
        "errors",
    ],
    "additionalProperties": False,
}

TOOL_DESCRIPTION = (
    "Use this tool when the user provides raw purchase order text and needs "
    "structured purchase order fields extracted from it. The tool returns "
    "purchase order number, supplier name, buyer name, item list, quantities, "
    "unit prices, currency, requested delivery date, shipping address, notes, "
    "missing fields, source text, and errors. Do not use this tool to create, "
    "approve, submit, modify, send, validate, or pay a purchase order. Do not "
    "use this tool to contact suppliers or update external systems. This tool "
    "is useful when deterministic structured extraction is needed instead of "
    "open-ended model summarization."
)

OUT_OF_SCOPE_PATTERNS = [
    r"\bapprove\b",
    r"\bcreate\b",
    r"\bsubmit\b",
    r"\bpay\b",
    r"\bpayment\b",
    r"\bemail\b",
    r"\bsend\b",
    r"\bcontact\b",
    r"\bupdate\b",
    r"\bmodify\b",
    r"\bvalidate\b",
    r"\bshould\s+we\b",
    r"\bdecision\b",
]


def blank_output(source_text="", status="error", errors=None):
    return {
        "status": status,
        "purchase_order_number": None,
        "supplier_name": None,
        "buyer_name": None,
        "items": [],
        "currency": None,
        "requested_delivery_date": None,
        "shipping_address": None,
        "notes": None,
        "missing_fields": [],
        "source_text": source_text,
        "errors": errors or [],
    }


def first_match(pattern, text, flags=re.IGNORECASE | re.MULTILINE):
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def parse_number(value):
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None


def parse_item_line(line):
    parts = [part.strip() for part in line.split(",") if part.strip()]
    item = {
        "item_name": parts[0] if parts else None,
        "sku": None,
        "quantity": None,
        "unit_price": None,
        "line_total": None,
    }

    field_patterns = {
        "sku": r"^SKU\s*:?\s*(.+)$",
        "quantity": r"^(?:Qty|Quantity)\s*:?\s*(\d+(?:\.\d+)?)$",
        "unit_price": r"^Unit\s+Price\s*:?\s*(\d+(?:,\d{3})*(?:\.\d+)?)$",
        "line_total": r"^Line\s+Total\s*:?\s*(\d+(?:,\d{3})*(?:\.\d+)?)$",
    }
    for part in parts[1:]:
        for field, pattern in field_patterns.items():
            match = re.match(pattern, part, re.IGNORECASE)
            if not match:
                continue
            if field == "sku":
                item[field] = match.group(1).strip()
            else:
                item[field] = parse_number(match.group(1))
            break
    return item


def extract_items(text):
    items = []
    item_line_pattern = re.compile(r"^\s*[-*]\s*(.+?)\s*$", re.MULTILINE)
    for match in item_line_pattern.finditer(text):
        items.append(parse_item_line(match.group(1)))
    return items


def is_out_of_scope(text):
    lowered = text.lower()
    extraction_terms = ("extract", "parse", "field", "fields")
    if any(term in lowered for term in extraction_terms):
        return False
    return any(re.search(pattern, lowered) for pattern in OUT_OF_SCOPE_PATTERNS)


def extract_purchase_order_fields(arguments):
    if not isinstance(arguments, dict) or "purchase_order_text" not in arguments:
        return blank_output(
            "",
            errors=[
                {
                    "error_type": "missing_field",
                    "message": "purchase_order_text is required",
                }
            ],
        )

    text = arguments.get("purchase_order_text")
    if not isinstance(text, str) or not text.strip():
        return blank_output(
            "" if not isinstance(text, str) else text,
            errors=[
                {
                    "error_type": "invalid_value",
                    "message": "purchase_order_text must be a non-empty string",
                }
            ],
        )

    if is_out_of_scope(text):
        return blank_output(
            text,
            errors=[
                {
                    "error_type": "out_of_scope",
                    "message": "This tool only extracts purchase order fields from provided text",
                }
            ],
        )

    output = blank_output(text, status="success", errors=[])
    output["purchase_order_number"] = first_match(
        r"\b(?:PO|Purchase\s+Order)\s*(?:#|Number|No\.?)?\s*:?\s*([A-Z0-9._-]+)",
        text,
    )
    output["supplier_name"] = first_match(r"^\s*Supplier\s*:\s*(.+)$", text)
    output["buyer_name"] = first_match(r"^\s*Buyer\s*:\s*(.+)$", text)
    output["items"] = extract_items(text)
    output["currency"] = first_match(r"^\s*Currency\s*:\s*([A-Z]{3})\s*$", text)
    output["requested_delivery_date"] = first_match(
        r"^\s*Requested\s+Delivery\s+Date\s*:\s*(\d{4}-\d{2}-\d{2})\s*$",
        text,
    )
    output["shipping_address"] = first_match(
        r"^\s*(?:Ship\s+to|Shipping\s+Address)\s*:\s*(.+)$",
        text,
    )
    output["notes"] = first_match(r"^\s*Notes\s*:\s*(.+)$", text)

    required_fields = [
        "purchase_order_number",
        "supplier_name",
        "buyer_name",
        "items",
        "currency",
        "requested_delivery_date",
        "shipping_address",
    ]
    output["missing_fields"] = [
        field for field in required_fields if not output.get(field)
    ]
    return output


def tool_definition():
    return {
        "name": TOOL_NAME,
        "title": "Purchase Order Field Extractor",
        "description": TOOL_DESCRIPTION,
        "inputSchema": INPUT_SCHEMA,
        "outputSchema": OUTPUT_SCHEMA,
        "annotations": ANNOTATIONS,
    }


def mcp_response(payload):
    method = payload.get("method")
    request_id = payload.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"},
            "capabilities": {"tools": {}},
        }
    elif method == "tools/list":
        result = {"tools": [tool_definition()]}
    elif method == "tools/call":
        params = payload.get("params") or {}
        name = params.get("name")
        if name != TOOL_NAME:
            content = blank_output(
                "",
                errors=[
                    {
                        "error_type": "out_of_scope",
                        "message": "Unknown tool for this app endpoint",
                    }
                ],
            )
        else:
            try:
                content = extract_purchase_order_fields(params.get("arguments") or {})
            except Exception:
                content = blank_output(
                    "",
                    errors=[
                        {
                            "error_type": "internal_error",
                            "message": "An internal extraction error occurred",
                        }
                    ],
                )
        result = {"structuredContent": content, "content": [{"type": "text", "text": json.dumps(content, sort_keys=True)}]}
    else:
        result = {
            "structuredContent": blank_output(
                "",
                errors=[
                    {
                        "error_type": "out_of_scope",
                        "message": "Unsupported MCP method for this app endpoint",
                    }
                ],
            )
        }

    return {"jsonrpc": "2.0", "id": request_id, "result": result}


class TaskAppHubHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_json(self, status, payload):
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html_file(self, filename):
        path = BASE_DIR / filename
        if not path.exists():
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        routes = {
            f"/{APP_SLUG}": f"{APP_KEY}_index.html",
            f"/{APP_SLUG}/privacy": f"{APP_KEY}_privacy.html",
            f"/{APP_SLUG}/terms": f"{APP_KEY}_terms.html",
            f"/{APP_SLUG}/support": f"{APP_KEY}_support.html",
        }
        if path == "/health":
            self.send_json(HTTPStatus.OK, {"status": "healthy"})
        elif path == "/.well-known/openai-apps-challenge":
            token = os.environ.get("OPENAI_APPS_CHALLENGE")
            self.send_json(
                HTTPStatus.OK,
                {"challenge": token or "local-development-challenge"},
            )
        elif path in routes:
            self.send_html_file(routes[path])
        else:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        if path != f"/{APP_SLUG}/mcp":
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                mcp_response({"id": None, "method": "tools/call", "params": {}}),
            )
            return
        self.send_json(HTTPStatus.OK, mcp_response(payload))


def create_server(port=None):
    selected_port = int(port or os.environ.get("PORT", "8000"))
    return ThreadingHTTPServer(("0.0.0.0", selected_port), TaskAppHubHandler)


if __name__ == "__main__":
    server = create_server()
    print(f"task-app-hub listening on port {server.server_port}")
    server.serve_forever()
