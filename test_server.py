import json
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server import APP_SLUG, TOOL_NAME, create_server


POSITIVE_TEXT = """PO #PO-10045
Supplier: Acme Office Supplies
Buyer: Northwind Traders
Items:
- Printer Paper, SKU PAP-001, Qty 10, Unit Price 5.50
- Ink Cartridge, SKU INK-220, Qty 2, Unit Price 39.99
Currency: USD
Requested Delivery Date: 2026-06-15
Ship to: 120 Market Street, San Francisco, CA 94105
Notes: Deliver during business hours."""


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
        return response.status, response.read().decode("utf-8")


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


def call_tool(base, arguments):
    payload = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": TOOL_NAME, "arguments": arguments},
    }
    status, body = post_json(base, f"/{APP_SLUG}/mcp", payload)
    return status, body["result"]["structuredContent"]


def test_server_starts_and_health(live_server):
    status, body = get_json(live_server, "/health")
    assert status == 200
    assert body == {"status": "healthy"}


def test_challenge_route(live_server):
    status, body = get_json(live_server, "/.well-known/openai-apps-challenge")
    assert status == 200
    assert "challenge" in body


@pytest.mark.parametrize(
    "path, expected",
    [
        (f"/{APP_SLUG}", "Purchase Order Field Extractor"),
        (f"/{APP_SLUG}/privacy", "does not store"),
        (f"/{APP_SLUG}/terms", "deterministic field extraction utility"),
        (f"/{APP_SLUG}/support", "sidcraigau@gmail.com"),
    ],
)
def test_review_pages(live_server, path, expected):
    status, body = get_text(live_server, path)
    assert status == 200
    assert expected in body


def test_initialize(live_server):
    status, body = post_json(
        live_server,
        f"/{APP_SLUG}/mcp",
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    result = body["result"]
    assert status == 200
    assert result["protocolVersion"]
    assert result["serverInfo"]["name"] == APP_SLUG
    assert "capabilities" in result


def test_tools_list_contract(live_server):
    status, body = post_json(
        live_server,
        f"/{APP_SLUG}/mcp",
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    tools = body["result"]["tools"]
    assert status == 200
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == TOOL_NAME
    assert tool["title"] == "Purchase Order Field Extractor"
    assert "description" in tool
    assert "inputSchema" in tool
    assert "outputSchema" in tool
    assert "annotations" in tool
    assert tool["annotations"] == {
        "readOnlyHint": True,
        "openWorldHint": False,
        "destructiveHint": False,
    }


def test_tools_call_positive_case(live_server):
    status, content = call_tool(
        live_server, {"purchase_order_text": POSITIVE_TEXT}
    )
    assert status == 200
    assert content["status"] == "success"
    assert content["purchase_order_number"] == "PO-10045"
    assert content["supplier_name"] == "Acme Office Supplies"
    assert content["buyer_name"] == "Northwind Traders"
    assert len(content["items"]) == 2
    assert content["items"][0]["quantity"] == 10.0
    assert content["items"][0]["unit_price"] == 5.5
    assert content["items"][0]["line_total"] == 55.0
    assert content["currency"] == "USD"
    assert content["requested_delivery_date"] == "2026-06-15"
    assert content["shipping_address"] == "120 Market Street, San Francisco, CA 94105"
    assert content["errors"] == []


def test_repeated_calls_are_stable(live_server):
    outputs = [
        call_tool(live_server, {"purchase_order_text": POSITIVE_TEXT})[1]
        for _ in range(3)
    ]
    assert outputs[0] == outputs[1] == outputs[2]


def test_missing_field_error(live_server):
    status, content = call_tool(live_server, {})
    assert status == 200
    assert content["status"] == "error"
    assert content["errors"] == [
        {
            "error_type": "missing_field",
            "message": "purchase_order_text is required",
        }
    ]


@pytest.mark.parametrize("value", ["", "   ", 42, None])
def test_invalid_value_error(live_server, value):
    status, content = call_tool(live_server, {"purchase_order_text": value})
    assert status == 200
    assert content["status"] == "error"
    assert content["errors"][0]["error_type"] == "invalid_value"


@pytest.mark.parametrize(
    "text",
    [
        "Approve this purchase order and send it to the supplier.",
        "Pay supplier Acme Office Supplies for PO-10045.",
        "Email this purchase order to the vendor.",
        "Should we approve this purchase order?",
    ],
)
def test_out_of_scope_error(live_server, text):
    status, content = call_tool(live_server, {"purchase_order_text": text})
    assert status == 200
    assert content["status"] == "error"
    assert content["errors"][0]["error_type"] == "out_of_scope"


def test_no_generic_mcp_endpoint(live_server):
    request = Request(
        f"{live_server}/mcp",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(HTTPError) as excinfo:
        urlopen(request, timeout=5)
    assert excinfo.value.code == 404
