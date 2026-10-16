# Experimental Kyckr MCP

An experimental FastMCP 4.1.0 version of the Kyckr MCP. It lives next to `services/kyckr-mcp` for comparison and serves the same seven tools with the same agent-facing text, titles, icons and system prompts:

- `search_companies`
- `get_lite_profile`
- `get_enhanced_profile`
- `list_company_documents`
- `create_document_order`
- `get_order`
- `list_orders`

Kyckr API errors come back as a structured `{ success: false, statusCode, message, correlationId }` reply, not an MCP error. A document order that has finished gets its JSON document inlined under `data.documentJson`, and download links are removed.

## How it is built

The tools are plain `@tool` functions. Each one calls Kyckr through an `OperationClient` from [`mcp-openapi`](../../packages/mcp-openapi), which builds the request from the vendored spec and parses the answer into a model generated from the same spec.

- `openapi/kyckr-openapi.yml`: Kyckr's Companies V2 spec, copied from `https://developer.kyckr.com/openapi/company_v2.yaml` so a restart never depends on that site. Lines marked `patched` differ from the published file because the API answers differently (order ids can be numbers, `POST /orders` and `GET /orders` carry the order and the page under `data`, and an enhanced profile can answer with a pending order).
- `models/vendor_responses.py` and `models/operations.py` are generated from it with `uv run scripts/generate_response_models.py`. Models keep fields the spec does not declare, so a new Kyckr field reaches the agent. A field of the wrong type fails on the server with an error that names it.
- `models/replies.py`: what each tool answers with. Every reply adds `success`, `statusCode` and `message` to the generated response, and leaves out empty fields. Each tool publishes its `data` type as its output schema.
- `params.py`: tool arguments. Trimming, upper-casing the ISO code and the 2-letter pattern are part of the published input schema.
- `orders.py`: the order logic, with no FastMCP in it. It reads the order out of either response shape and fetches the JSON document of a finished order. A 404 or a body that is not JSON on that download means the filing is PDF-only, and `details` says so. Any other failure of the download keeps the order and tells the agent to call `get_order` again.
- `failures.py`: turns a failed Kyckr call into the failed reply of the tool's own type.
- `tools/`: `companies.py` and `orders.py`. `FileSystemProvider` registers every `@tool` in them.
- `hints.py`: the title, annotations, icon and system prompt each tool sets for the Unique platform.
- `client.py`: the HTTP client. It sends only an allow-list of headers, sets the Kyckr key on requests to the Kyckr origin only, and records metrics and spans.

### Refreshing the spec

Download the new file over `openapi/kyckr-openapi.yml`, apply the `patched` changes again (or drop one that Kyckr has fixed), run the generator, and review the diff of the generated models. Nothing is refreshed on its own.

## Run

```sh
cp .env.example .env
# Set MCP_API_KEY and KYCKR_API_KEY.
uv run kyckr-mcp
```

The MCP endpoint is available at `http://127.0.0.1:9542/$MCP_API_KEY/mcp`. The shared `unique_mcp` runtime also exposes `/probe`, `/health`, and `/metrics`.

## Metrics and tracing

`/metrics` carries the shared `mcp_calls_total` and `mcp_call_duration_seconds` per tool, plus `kyckr_api_requests_total`, `kyckr_api_request_duration_seconds`, and `kyckr_credits_consumed_total` for calls to Kyckr. Credits count only on paid calls (lite profile, enhanced profile, order creation) that succeed. The `path` label is the route template, never a raw id.

Tracing is off unless `OTEL_TRACES_EXPORTER` or `OTEL_EXPORTER_OTLP_ENDPOINT` is set. FastMCP emits the tool spans, and each Kyckr call adds a child span. Calls that fail before a response arrives (timeouts, connection errors) are not counted or traced.

## Checks

```sh
uv run ruff format .
uv run ruff check .
uv run basedpyright
uv run pytest
```
