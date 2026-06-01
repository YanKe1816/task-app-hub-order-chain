import json
import os
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server import (
    ANNOTATIONS,
    APP_SLUG,
    INVOICE_APP_SLUG,
    INVOICE_OUTPUT_SCHEMA,
    INVOICE_TOOL_NAME,
    OUTPUT_SCHEMA,
    SHIPPING_ANNOTATIONS,
    SHIPPING_APP_SLUG,
    SHIPPING_OUTPUT_SCHEMA,
    SHIPPING_TOOL_NAME,
    TOOL_NAME,
    create_server,
)


PURCHASE_ORDER_POSITIVE_TEXT = """Purchase Order PO-10045
Supplier: Acme Office Supplies
Buyer: Northwind Retail LLC
Items:
- Ergonomic Chair, SKU CH-778, Quantity 5, Unit Price 129.99
- Standing Desk, SKU DK-221, Quantity 2, Unit Price 349.50
Currency: USD
Requested Delivery Date: 2026-06-15
Shipping Address: 120 Market Street, Austin, TX 78701
Notes: Deliver during business hours."""

PURCHASE_ORDER_MISSING_FIELD_TEXT = """PO Number: PO-20018
Supplier: Green Valley Foods
Items:
- Organic Apples, SKU APP-101, Quantity 20, Unit Price 1.25
Currency: USD"""

INVOICE_POSITIVE_TEXT = """Invoice Number: INV-2026-1188
Supplier: Northline Office Supply
Buyer: Brightway Retail LLC
Invoice Date: 2026-06-01
Due Date: 2026-06-30
Items:
- Printer Paper A4, SKU A4-500, Quantity 20, Unit Price 6.50, Line Total 130.00
- Black Ink Cartridge, SKU INK-BLK, Quantity 5, Unit Price 24.00, Line Total 120.00
Subtotal: 250.00
Tax: 20.00
Total Amount: 270.00
Currency: USD
Billing Address: 18 Market Street, Boston, MA 02110
Payment Terms: Net 30"""

SHIPPING_POSITIVE_TEXT = "Shipping delay notice for Order ORD-7821. Carrier: FastShip Express. Tracking Number: FSX991882. The package was originally expected to arrive on 2026-06-12, but due to severe weather at the regional hub, the new estimated delivery date is 2026-06-15. Affected items: Wireless Keyboard and USB-C Dock. Customer notice: Your shipment is delayed due to weather conditions. We apologize for the inconvenience."

SHIPPING_MINIMAL_TEXT = "Order ORD-4408 is delayed. Carrier: Northline Logistics. New estimated delivery date: 2026-06-20."

SHIPPING_BULLET_ITEMS_TEXT = """Shipping delay notice for Order ORD-7821.
Carrier: FastShip Express.
Tracking Number: FSX991882.
Affected items:
- Wireless Keyboard
- USB-C Dock"""

SHIPPING_SOFT_DELAY_TEXT = """Delay update:
Order ORD-9033 will not arrive on the original delivery date.
The delay was caused by customs inspection.
The new delivery estimate is next Monday."""


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def live_server():
    port = free_port()
    server = create_server(port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def get_json(base, path):
    with urlopen(f"{base}{path}", timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def get_text(base, path):
    with urlopen(f"{base}{path}", timeout=5) as response:
        return (
            response.status,
            response.read().decode("utf-8"),
            response.headers.get("Content-Type"),
        )


def post_json(base, path, payload):
    data = json.dumps(payload).encode("utf-8")
    request = Request(
        f"{base}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def call_tool(base, slug, tool_name, arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    status, body = post_json(base, f"/{slug}/mcp", payload)
    return status, body["result"]


def assert_value_matches_schema(value, schema):
    schema_type = schema.get("type")
    allowed_types = schema_type if isinstance(schema_type, list) else [schema_type]
    if value is None:
        assert "null" in allowed_types
        return
    if "string" in allowed_types:
        assert isinstance(value, str)
        return
    if "number" in allowed_types:
        assert isinstance(value, (int, float)) and not isinstance(value, bool)
        return
    if "array" in allowed_types:
        assert isinstance(value, list)
        for item in value:
            assert_value_matches_schema(item, schema["items"])
        return
    if "object" in allowed_types:
        assert isinstance(value, dict)
        assert set(schema["required"]).issubset(value.keys())
        if schema.get("additionalProperties") is False:
            assert set(value.keys()).issubset(schema["properties"].keys())
        for key, property_schema in schema["properties"].items():
            if key in value:
                assert_value_matches_schema(value[key], property_schema)
        return
    if "boolean" in allowed_types:
        assert isinstance(value, bool)
        return
    raise AssertionError(f"Unsupported schema type: {schema_type}")


def test_server_starts_and_health(live_server):
    status, body = get_json(live_server, "/health")
    assert status == 200
    assert body == {"status": "healthy"}


def test_challenge_route(live_server):
    expected = "weyl2ueRDCgpcUPa8PTYVbPDpetTeH79IQ97TvA0tn0"
    original = os.environ.get("OPENAI_APPS_CHALLENGE")
    os.environ["OPENAI_APPS_CHALLENGE"] = expected
    try:
        status, body, content_type = get_text(
            live_server, "/.well-known/openai-apps-challenge"
        )
    finally:
        if original is None:
            os.environ.pop("OPENAI_APPS_CHALLENGE", None)
        else:
            os.environ["OPENAI_APPS_CHALLENGE"] = original
    assert status == 200
    assert body == expected
    assert content_type.startswith("text/plain")


def test_challenge_route_has_plain_text_local_fallback(live_server):
    original = os.environ.get("OPENAI_APPS_CHALLENGE")
    os.environ.pop("OPENAI_APPS_CHALLENGE", None)
    try:
        status, body, content_type = get_text(
            live_server, "/.well-known/openai-apps-challenge"
        )
    finally:
        if original is not None:
            os.environ["OPENAI_APPS_CHALLENGE"] = original
    assert status == 200
    assert body == "local-openai-apps-challenge"
    assert not body.startswith("{")
    assert content_type.startswith("text/plain")


@pytest.mark.parametrize(
    "path, expected, expected_links",
    [
        (
            f"/{APP_SLUG}",
            "Purchase Order Field Extractor",
            [
                f"/{APP_SLUG}/privacy",
                f"/{APP_SLUG}/terms",
                f"/{APP_SLUG}/support",
            ],
        ),
        (
            f"/{APP_SLUG}/privacy",
            "does not store",
            [f"/{APP_SLUG}", f"/{APP_SLUG}/terms", f"/{APP_SLUG}/support"],
        ),
        (
            f"/{APP_SLUG}/terms",
            "deterministic field extraction utility",
            [f"/{APP_SLUG}", f"/{APP_SLUG}/privacy", f"/{APP_SLUG}/support"],
        ),
        (
            f"/{APP_SLUG}/support",
            "sidcraigau@gmail.com",
            [f"/{APP_SLUG}", f"/{APP_SLUG}/privacy", f"/{APP_SLUG}/terms"],
        ),
        (
            f"/{INVOICE_APP_SLUG}",
            "Invoice Field Extractor",
            [
                f"/{INVOICE_APP_SLUG}/privacy",
                f"/{INVOICE_APP_SLUG}/terms",
                f"/{INVOICE_APP_SLUG}/support",
            ],
        ),
        (
            f"/{INVOICE_APP_SLUG}/privacy",
            "does not store",
            [
                f"/{INVOICE_APP_SLUG}",
                f"/{INVOICE_APP_SLUG}/terms",
                f"/{INVOICE_APP_SLUG}/support",
            ],
        ),
        (
            f"/{INVOICE_APP_SLUG}/terms",
            "deterministic field extraction utility",
            [
                f"/{INVOICE_APP_SLUG}",
                f"/{INVOICE_APP_SLUG}/privacy",
                f"/{INVOICE_APP_SLUG}/support",
            ],
        ),
        (
            f"/{INVOICE_APP_SLUG}/support",
            "sidcraigau@gmail.com",
            [
                f"/{INVOICE_APP_SLUG}",
                f"/{INVOICE_APP_SLUG}/privacy",
                f"/{INVOICE_APP_SLUG}/terms",
            ],
        ),
        (
            f"/{SHIPPING_APP_SLUG}",
            "Shipping Delay Extractor",
            [
                "/",
                f"/{SHIPPING_APP_SLUG}/privacy",
                f"/{SHIPPING_APP_SLUG}/terms",
                f"/{SHIPPING_APP_SLUG}/support",
            ],
        ),
        (
            f"/{SHIPPING_APP_SLUG}/privacy",
            "does not store data",
            [
                f"/{SHIPPING_APP_SLUG}",
                f"/{SHIPPING_APP_SLUG}/terms",
                f"/{SHIPPING_APP_SLUG}/support",
            ],
        ),
        (
            f"/{SHIPPING_APP_SLUG}/terms",
            "deterministic field extraction utility",
            [
                f"/{SHIPPING_APP_SLUG}",
                f"/{SHIPPING_APP_SLUG}/privacy",
                f"/{SHIPPING_APP_SLUG}/support",
            ],
        ),
        (
            f"/{SHIPPING_APP_SLUG}/support",
            "sidcraigau@gmail.com",
            [
                f"/{SHIPPING_APP_SLUG}",
                f"/{SHIPPING_APP_SLUG}/privacy",
                f"/{SHIPPING_APP_SLUG}/terms",
            ],
        ),
    ],
)
def test_review_pages(live_server, path, expected, expected_links):
    status, body, _ = get_text(live_server, path)
    assert status == 200
    assert expected in body
    for link in expected_links:
        assert f'href="{link}"' in body


@pytest.mark.parametrize(
    "slug, server_name",
    [
        (APP_SLUG, APP_SLUG),
        (INVOICE_APP_SLUG, INVOICE_APP_SLUG),
        (SHIPPING_APP_SLUG, SHIPPING_APP_SLUG),
    ],
)
def test_initialize(live_server, slug, server_name):
    status, body = post_json(
        live_server,
        f"/{slug}/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    result = body["result"]
    assert status == 200
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == server_name
    assert "capabilities" in result


@pytest.mark.parametrize(
    "slug, tool_name, title, output_schema, annotations",
    [
        (
            APP_SLUG,
            TOOL_NAME,
            "Purchase Order Field Extractor",
            OUTPUT_SCHEMA,
            ANNOTATIONS,
        ),
        (
            INVOICE_APP_SLUG,
            INVOICE_TOOL_NAME,
            "Invoice Field Extractor",
            INVOICE_OUTPUT_SCHEMA,
            ANNOTATIONS,
        ),
        (
            SHIPPING_APP_SLUG,
            SHIPPING_TOOL_NAME,
            "Shipping Delay Extractor",
            SHIPPING_OUTPUT_SCHEMA,
            SHIPPING_ANNOTATIONS,
        ),
    ],
)
def test_tools_list_contract(
    live_server, slug, tool_name, title, output_schema, annotations
):
    status, body = post_json(
        live_server,
        f"/{slug}/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    tools = body["result"]["tools"]
    assert status == 200
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == tool_name
    assert tool["title"] == title
    assert "description" in tool
    assert "inputSchema" in tool
    assert "outputSchema" in tool
    assert tool["outputSchema"] == output_schema
    assert tool["annotations"] == annotations


def test_purchase_order_tools_call_positive_case(live_server):
    status, result = call_tool(
        live_server,
        APP_SLUG,
        TOOL_NAME,
        {"purchase_order_text": PURCHASE_ORDER_POSITIVE_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["purchase_order_number"] == "PO-10045"
    assert content["supplier_name"] == "Acme Office Supplies"
    assert content["buyer_name"] == "Northwind Retail LLC"
    assert len(content["items"]) == 2
    assert content["items"][0] == {
        "item_name": "Ergonomic Chair",
        "sku": "CH-778",
        "quantity": 5.0,
        "unit_price": 129.99,
        "line_total": None,
    }
    assert content["items"][1] == {
        "item_name": "Standing Desk",
        "sku": "DK-221",
        "quantity": 2.0,
        "unit_price": 349.5,
        "line_total": None,
    }
    assert content["currency"] == "USD"
    assert content["requested_delivery_date"] == "2026-06-15"
    assert content["shipping_address"] == "120 Market Street, Austin, TX 78701"
    assert content["notes"] == "Deliver during business hours."
    assert content["missing_fields"] == []
    assert content["errors"] == []


def test_invoice_tools_call_positive_case(live_server):
    status, result = call_tool(
        live_server,
        INVOICE_APP_SLUG,
        INVOICE_TOOL_NAME,
        {"invoice_text": INVOICE_POSITIVE_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert "structuredContent" in result
    assert_value_matches_schema(content, INVOICE_OUTPUT_SCHEMA)
    assert content["status"] == "success"
    assert content["invoice_number"] == "INV-2026-1188"
    assert content["supplier"] == "Northline Office Supply"
    assert content["buyer"] == "Brightway Retail LLC"
    assert content["invoice_date"] == "2026-06-01"
    assert content["due_date"] == "2026-06-30"
    assert content["currency"] == "USD"
    assert content["subtotal"] == 250.0
    assert content["tax_amount"] == 20.0
    assert content["total_amount"] == 270.0
    assert content["billing_address"] == "18 Market Street, Boston, MA 02110"
    assert content["payment_terms"] == "Net 30"
    assert content["line_items"] == [
        {
            "item_name": "Printer Paper A4",
            "sku": "A4-500",
            "quantity": 20.0,
            "unit_price": 6.5,
            "line_total": 130.0,
        },
        {
            "item_name": "Black Ink Cartridge",
            "sku": "INK-BLK",
            "quantity": 5.0,
            "unit_price": 24.0,
            "line_total": 120.0,
        },
    ]
    assert content["missing_fields"] == []
    assert content["errors"] == []


def test_shipping_delay_tools_call_positive_case(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {"notice_text": SHIPPING_POSITIVE_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert_value_matches_schema(content, SHIPPING_OUTPUT_SCHEMA)
    assert content["status"] == "success"
    assert content["is_shipping_delay_notice"] is True
    assert content["order_number"] == "ORD-7821"
    assert content["carrier"] == "FastShip Express"
    assert content["tracking_number"] == "FSX991882"
    assert content["delay_reason"] == "severe weather at the regional hub"
    assert content["original_estimated_delivery_date"] == "2026-06-12"
    assert content["new_estimated_delivery_date"] == "2026-06-15"
    assert content["affected_items"] == ["Wireless Keyboard", "USB-C Dock"]
    assert content["customer_notice"] == (
        "Your shipment is delayed due to weather conditions. We apologize for the inconvenience."
    )
    assert content["confidence"] == "high"


def test_shipping_delay_tools_call_minimal_case(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {"notice_text": SHIPPING_MINIMAL_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["is_shipping_delay_notice"] is True
    assert content["order_number"] == "ORD-4408"
    assert content["carrier"] == "Northline Logistics"
    assert content["new_estimated_delivery_date"] == "2026-06-20"
    assert set(content["missing_fields"]) == {
        "tracking_number",
        "delay_reason",
        "original_estimated_delivery_date",
        "affected_items",
        "affected_scope",
        "customer_notice",
    }


def test_shipping_delay_extracts_multiline_affected_items(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {"notice_text": SHIPPING_BULLET_ITEMS_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["is_shipping_delay_notice"] is True
    assert content["affected_items"] == ["Wireless Keyboard", "USB-C Dock"]


def test_shipping_delay_soft_delay_update_case(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {"notice_text": SHIPPING_SOFT_DELAY_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["is_shipping_delay_notice"] is True
    assert content["order_number"] == "ORD-9033"
    assert content["delay_reason"] == "customs inspection"
    assert content["new_estimated_delivery_date"] == "next Monday"


def test_purchase_order_missing_field_extraction_stays_successful(live_server):
    status, result = call_tool(
        live_server,
        APP_SLUG,
        TOOL_NAME,
        {"purchase_order_text": PURCHASE_ORDER_MISSING_FIELD_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["purchase_order_number"] == "PO-20018"
    assert content["supplier_name"] == "Green Valley Foods"
    assert content["buyer_name"] is None
    assert content["requested_delivery_date"] is None
    assert content["shipping_address"] is None
    assert set(content["missing_fields"]) == {
        "buyer_name",
        "requested_delivery_date",
        "shipping_address",
    }
    assert content["errors"] == []


@pytest.mark.parametrize(
    "slug, tool_name, arguments",
    [
        (APP_SLUG, TOOL_NAME, {"purchase_order_text": PURCHASE_ORDER_POSITIVE_TEXT}),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {"invoice_text": INVOICE_POSITIVE_TEXT}),
        (SHIPPING_APP_SLUG, SHIPPING_TOOL_NAME, {"notice_text": SHIPPING_POSITIVE_TEXT}),
    ],
)
def test_repeated_calls_are_stable(live_server, slug, tool_name, arguments):
    outputs = [
        call_tool(live_server, slug, tool_name, arguments)[1]["structuredContent"]
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]


@pytest.mark.parametrize(
    "slug, tool_name, arguments, error_key, expected_error",
    [
        (APP_SLUG, TOOL_NAME, {}, "error_type", "missing_field"),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {}, "code", "missing_field"),
        (SHIPPING_APP_SLUG, SHIPPING_TOOL_NAME, {}, None, None),
    ],
)
def test_missing_field_error(
    live_server, slug, tool_name, arguments, error_key, expected_error
):
    status, result = call_tool(live_server, slug, tool_name, arguments)
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "error"
    if slug == SHIPPING_APP_SLUG:
        assert content["missing_fields"] == ["notice_text"]
        assert content["warnings"] == [
            "notice_text is required and must be a non-empty string."
        ]
    else:
        assert content["errors"][0][error_key] == expected_error


@pytest.mark.parametrize(
    "slug, tool_name, arguments, error_key",
    [
        (APP_SLUG, TOOL_NAME, {"purchase_order_text": ""}, "error_type"),
        (APP_SLUG, TOOL_NAME, {"purchase_order_text": "   "}, "error_type"),
        (APP_SLUG, TOOL_NAME, {"purchase_order_text": 42}, "error_type"),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {"invoice_text": ""}, "code"),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {"invoice_text": "   "}, "code"),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {"invoice_text": 42}, "code"),
        (INVOICE_APP_SLUG, INVOICE_TOOL_NAME, {"invoice_text": "hello world"}, "code"),
        (SHIPPING_APP_SLUG, SHIPPING_TOOL_NAME, {"notice_text": ""}, None),
        (SHIPPING_APP_SLUG, SHIPPING_TOOL_NAME, {"notice_text": "   "}, None),
        (SHIPPING_APP_SLUG, SHIPPING_TOOL_NAME, {"notice_text": 42}, None),
    ],
)
def test_invalid_value_error(live_server, slug, tool_name, arguments, error_key):
    status, result = call_tool(live_server, slug, tool_name, arguments)
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "error"
    if slug == SHIPPING_APP_SLUG:
        assert content["missing_fields"] == ["notice_text"]
        assert content["warnings"] == [
            "notice_text is required and must be a non-empty string."
        ]
    else:
        assert content["errors"][0][error_key] == "invalid_value"


@pytest.mark.parametrize(
    "slug, tool_name, arguments, error_key",
    [
        (
            APP_SLUG,
            TOOL_NAME,
            {"purchase_order_text": "Approve this purchase order and send it."},
            "error_type",
        ),
        (
            INVOICE_APP_SLUG,
            INVOICE_TOOL_NAME,
            {"invoice_text": "Should we approve this invoice?"},
            "code",
        ),
        (
            INVOICE_APP_SLUG,
            INVOICE_TOOL_NAME,
            {"invoice_text": "Please pay this invoice now."},
            "code",
        ),
        (
            INVOICE_APP_SLUG,
            INVOICE_TOOL_NAME,
            {"invoice_text": "Can you give me tax advice for this invoice?"},
            "code",
        ),
        (
            INVOICE_APP_SLUG,
            INVOICE_TOOL_NAME,
            {"invoice_text": "Write an email to the supplier about this invoice."},
            "code",
        ),
    ],
)
def test_out_of_scope_error(live_server, slug, tool_name, arguments, error_key):
    status, result = call_tool(live_server, slug, tool_name, arguments)
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "error"
    assert content["errors"][0][error_key] == "out_of_scope"


def test_shipping_delay_non_notice_returns_structured_no_extraction(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {"notice_text": "Please approve a payment for this vendor."},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content == {
        "status": "success",
        "is_shipping_delay_notice": False,
        "order_number": None,
        "carrier": None,
        "tracking_number": None,
        "delay_reason": None,
        "original_estimated_delivery_date": None,
        "new_estimated_delivery_date": None,
        "affected_items": [],
        "affected_scope": None,
        "customer_notice": None,
        "confidence": "low",
        "missing_fields": [],
        "warnings": [
            "The input does not appear to be a shipping delay notice. No shipping delay fields were extracted."
        ],
    }


def test_shipping_delay_out_of_scope_compensation_warning(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        SHIPPING_TOOL_NAME,
        {
            "notice_text": "Should we compensate this customer for the late delivery? Order ORD-7821 was delayed by FastShip Express."
        },
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "success"
    assert content["is_shipping_delay_notice"] is True
    assert content["order_number"] == "ORD-7821"
    assert content["carrier"] == "FastShip Express"
    assert content["warnings"] == [
        "Compensation, refund, approval, responsibility, messaging, carrier contact, order modification, and rescheduling decisions are out of scope."
    ]


def test_shipping_delay_wrong_tool_name_returns_unknown_tool_warning(live_server):
    status, result = call_tool(
        live_server,
        SHIPPING_APP_SLUG,
        "wrong_tool",
        {"notice_text": SHIPPING_POSITIVE_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content == {
        "status": "error",
        "is_shipping_delay_notice": False,
        "order_number": None,
        "carrier": None,
        "tracking_number": None,
        "delay_reason": None,
        "original_estimated_delivery_date": None,
        "new_estimated_delivery_date": None,
        "affected_items": [],
        "affected_scope": None,
        "customer_notice": None,
        "confidence": "low",
        "missing_fields": [],
        "warnings": ["Unknown tool for this app endpoint."],
    }


def test_cross_endpoint_tool_is_rejected(live_server):
    status, result = call_tool(
        live_server,
        INVOICE_APP_SLUG,
        TOOL_NAME,
        {"invoice_text": INVOICE_POSITIVE_TEXT},
    )
    content = result["structuredContent"]
    assert status == 200
    assert content["status"] == "error"
    assert content["errors"][0]["code"] == "out_of_scope"


def test_no_generic_mcp_endpoint(live_server):
    request = Request(
        f"{live_server}/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(
            "utf-8"
        ),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as excinfo:
        urlopen(request, timeout=5)
    assert excinfo.value.code == 404
