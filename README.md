# task-app-hub

Shared Task App Hub hosting independent Task Apps under one Python HTTP server.

## Current apps

- App: Purchase Order Field Extractor
- Slug: `purchase-order-field-extractor`
- MCP endpoint: `/purchase-order-field-extractor/mcp`
- Tool: `purchase_order_field_extractor`
- App: Invoice Field Extractor
- Slug: `invoice-field-extractor`
- MCP endpoint: `/invoice-field-extractor/mcp`
- Tool: `invoice_field_extractor`
- App: Shipping Delay Extractor
- Slug: `shipping-delay-extractor`
- MCP endpoint: `/shipping-delay-extractor/mcp`
- Tool: `shipping_delay_extractor`

## Run locally

```powershell
python server.py
```

The server uses `PORT` when set and defaults to `8000`.

## Test

```powershell
python -m pytest
```

## Routes

- `GET /health`
- `GET /.well-known/openai-apps-challenge`
- `GET /purchase-order-field-extractor`
- `POST /purchase-order-field-extractor/mcp`
- `GET /purchase-order-field-extractor/privacy`
- `GET /purchase-order-field-extractor/terms`
- `GET /purchase-order-field-extractor/support`
- `GET /invoice-field-extractor`
- `POST /invoice-field-extractor/mcp`
- `GET /invoice-field-extractor/privacy`
- `GET /invoice-field-extractor/terms`
- `GET /invoice-field-extractor/support`
- `GET /shipping-delay-extractor`
- `POST /shipping-delay-extractor/mcp`
- `GET /shipping-delay-extractor/privacy`
- `GET /shipping-delay-extractor/terms`
- `GET /shipping-delay-extractor/support`

There is no generic shared `/mcp` endpoint.
