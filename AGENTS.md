# Task App Hub Production Rules

Project name: `task-app-hub`

Production mode: Multi-App Hub mode

This repository hosts multiple independent Task Apps under one shared server.
These rules are permanent production instructions for all future work in this
project.

## Core Architecture

- Use one shared server.
- Host multiple independent app branches.
- Each app branch owns exactly these routes:
  - `/{app-slug}`
  - `/{app-slug}/mcp`
  - `/{app-slug}/privacy`
  - `/{app-slug}/terms`
  - `/{app-slug}/support`
- Each app branch must expose exactly one MCP tool.
- One App = one MCP endpoint = one tool = one clear task station.

## Global Hard Rules

1. Do not create a generic shared `/mcp` endpoint.
2. Do not expose all tools under one endpoint.
3. Each app MCP endpoint must be `/{app-slug}/mcp`.
4. Each `/{app-slug}/mcp` endpoint must expose only that app's own tool.
5. Do not add authentication unless explicitly required.
6. Do not add database storage.
7. Do not add persistent state.
8. Do not call external APIs.
9. Do not write to external systems.
10. Do not create, update, submit, approve, send, delete, or modify real-world records.
11. Keep every app stateless, deterministic, read-only, and review-friendly.
12. Do not build complex UI.
13. Do not build a marketing site.
14. Do not add unrelated app routes.
15. Do not add multiple tools to one app.
16. Do not refactor old apps unless required to preserve routing safely.
17. Future apps must not break existing apps.

## Gate System

- Gate 1: Plan
- Gate 2: Build + Connect + Review Pages
- Gate 3: Deploy + Online Verification
- Gate 4: Submission Materials + Official Submit
- Gate 5: Review Result Handling

## Gate 2 Requirements

Gate 2 must deliver a local complete version. It must include:

- independent MCP endpoint
- `initialize`
- `tools/list`
- `tools/call`
- complete tool description
- complete `inputSchema`
- complete `outputSchema`
- annotations
- Error Contract
- deterministic tool logic
- formal HTML review pages
- `/health`
- `/.well-known/openai-apps-challenge`
- `requirements.txt`
- `render.yaml` or deploy-ready equivalent
- tests
- self-verification report

## Formal HTML Page Rule

Do not put large HTML pages directly inside `server.py`.
Create independent HTML files for every app:

- `{app_key}_index.html`
- `{app_key}_privacy.html`
- `{app_key}_terms.html`
- `{app_key}_support.html`

## MCP Initialize Rule

Each app MCP endpoint must support `initialize`.

The `initialize` response must include:

- `protocolVersion`
- `serverInfo`
- `capabilities`

## MCP Tools/List Rule

Each app MCP endpoint must support `tools/list`.

`tools/list` must return exactly one tool for the current app.

The tool definition must include:

- `name`
- `title`
- `description`
- `inputSchema`
- `outputSchema`
- `annotations`

## MCP Tools/Call Rule

Each app MCP endpoint must support `tools/call`.

`tools/call` must return `structuredContent`.

The output must follow the declared `outputSchema`.
The same input must produce the same structure.
Do not return open-ended advice.
Do not generate long natural-language answers as the main output.

## Default Annotations

```json
{
  "readOnlyHint": true,
  "openWorldHint": false,
  "destructiveHint": false
}
```

## Error Contract

Every tool must support structured errors. At minimum support:

- `missing_field`
- `invalid_value`
- `out_of_scope`
- `internal_error`

Error outputs must still match the declared `outputSchema`.

## Testing Rule

For each current app, add or update tests for:

1. server starts
2. `GET /health`
3. `GET /.well-known/openai-apps-challenge`
4. `GET /{app-slug}`
5. `GET /{app-slug}/privacy`
6. `GET /{app-slug}/terms`
7. `GET /{app-slug}/support`
8. `POST /{app-slug}/mcp initialize`
9. `POST /{app-slug}/mcp tools/list`
10. `tools/list` exposes only the current app tool
11. `tools/list` includes `inputSchema`
12. `tools/list` includes `outputSchema`
13. `tools/list` includes `annotations`
14. `POST /{app-slug}/mcp tools/call` positive case
15. missing required input returns structured error
16. invalid input returns structured error
17. out-of-scope input returns structured error
18. three repeated calls with the same input return stable structure
19. no generic `/mcp` endpoint exposing all tools

For future apps, regression tests must confirm all existing app endpoints still
work and still expose only their own tool.

## Expected Base Files

- `AGENTS.md`
- `server.py`
- `test_server.py`
- `requirements.txt`
- `render.yaml`
- `README.md`
- independent HTML files for each app

