import json
import socket
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server import APP_SLUG, TOOL_NAME, create_server


POSITIVE_TEXT = """Purchase Order PO-10045
Supplier: Acme Office Supplies
Buyer: Northwind Retail LLC
Items:
- Ergonomic Chair, SKU CH-778, Quantity 5, Unit Price 129.99
- Standing Desk, SKU DK-221, Quantity 2, Unit Price 349.50
Currency: USD
Requested Delivery Date: 2026-06-15
Shipping Address: 120 Market Street, Austin, TX 78701
Notes: Deliver during business hours."""

MISSING_FIELD_TEXT = """PO Number: PO-20018
Supplier: Green Valley Foods
Items:
- Organic Apples, SKU APP-101, Quantity 20, Unit Price 1.25
Currency: USD"""


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


def test_sku_extraction(live_server):
    _, content = call_tool(live_server, {"purchase_order_text": POSITIVE_TEXT})
    assert [item["sku"] for item in content["items"]] == ["CH-778", "DK-221"]


def test_quantity_extraction(live_server):
    _, content = call_tool(live_server, {"purchase_order_text": POSITIVE_TEXT})
    assert [item["quantity"] for item in content["items"]] == [5.0, 2.0]


def test_shipping_address_extraction(live_server):
    _, content = call_tool(live_server, {"purchase_order_text": POSITIVE_TEXT})
    assert content["shipping_address"] == "120 Market Street, Austin, TX 78701"


def test_missing_field_extraction_stays_successful(live_server):
    status, content = call_tool(
        live_server, {"purchase_order_text": MISSING_FIELD_TEXT}
    )
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
    assert content["items"][0] == {
        "item_name": "Organic Apples",
        "sku": "APP-101",
        "quantity": 20.0,
        "unit_price": 1.25,
        "line_total": None,
    }
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
