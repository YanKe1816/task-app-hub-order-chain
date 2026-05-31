# task-app-hub

Shared Task App Hub hosting independent Task Apps under one Python HTTP server.

## Current app

- App: Purchase Order Field Extractor
- Slug: `purchase-order-field-extractor`
- MCP endpoint: `/purchase-order-field-extractor/mcp`
- Tool: `purchase_order_field_extractor`

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

There is no generic shared `/mcp` endpoint.
