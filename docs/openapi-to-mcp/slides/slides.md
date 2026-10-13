---
theme: default
title: From an OpenAPI spec to an MCP server
info: A FastMCP tutorial, with the experimental Tiingo MCP as the worked example
highlighter: shiki
lineNumbers: false
transition: fade
mdc: true
---

# From an OpenAPI spec to an MCP server

Generating connector tools with FastMCP, and what we learned doing it for Tiingo, a market-data API

<div class="pt-4 opacity-70">
FastMCP 4.1.0
</div>

---

# The pipeline

<div class="pipeline">
  <div class="col">
    <div class="step"><b>OpenAPI spec</b><small>3.0 or 3.1</small></div>
    <div class="down">↓</div>
    <div class="step ti"><small>vendored YAML, patched</small></div>
  </div>
  <div class="col">
    <div class="step"><b>Route maps</b><small>what is exposed</small></div>
    <div class="down">↓</div>
    <div class="step ti"><small>allow-list, 13 operations</small></div>
  </div>
  <div class="col">
    <div class="step"><b>Generated tools</b><small>one per operation</small></div>
    <div class="down">↓</div>
    <div class="step ti"><small>12 tools + 1 resource</small></div>
  </div>
  <div class="col">
    <div class="step"><b>Transforms</b><small>what the LLM sees</small></div>
    <div class="down">↓</div>
    <div class="step ti"><small>3 wrapped + 1 chart tool</small></div>
  </div>
  <div class="col">
    <div class="step"><b>MCP server</b><small>one HTTP client</small></div>
    <div class="down">↓</div>
    <div class="step ti"><small>Token auth, one client</small></div>
  </div>
</div>

<div class="pt-10 caption">
Part 1 walks the <span class="tag">pipeline</span> for any spec. The <span class="tag ti">purple row</span> is the Tiingo MCP, the subject of Part 2.
</div>

---
layout: section
---

# Part 1
## Starting from any OpenAPI spec

---

# What the spec gives you

`FastMCP.from_openapi(spec)` builds one MCP tool per operation by default.

| In the spec | On the MCP tool |
|---|---|
| `operationId` | tool name (slugified, `mcp_names` overrides) |
| `description`, else `summary` | tool description |
| path, query, header and body parameters | input schema |
| the first `2xx` response schema | output schema |

The LLM sees only what the spec says, so vague descriptions and wrong schemas go straight into the tools.

---

# Loading the spec

`from_openapi` takes a dict, so you parse the file.

```py
spec = yaml.safe_load(Path("openapi.yml").read_text())

resp = httpx2.get("https://api.example.com/openapi.json")
resp.raise_for_status()
spec = resp.json()
```

<div class="cards">
  <div class="card">
    <h3>Vendored copy</h3>
    Reproducible, and you can patch it.
  </div>
  <div class="card">
    <h3>Fetched at startup</h3>
    Always current, but startup needs the network.
  </div>
</div>

OpenAPI 3.0 and 3.1 work. Swagger 2.0 loads without an error once you pass a client, but the tools get untyped inputs and no output schemas, so convert it first:

```sh
npx swagger2openapi swagger.json -o openapi.json
```

---
layout: two-cols
---

# The client

Every tool call is an HTTP request through the `httpx2.AsyncClient` you pass in (the HTTP library FastMCP 4 uses).

Base URL, auth, timeout, `follow_redirects` and `event_hooks` all live on it.

Without a client, FastMCP uses the first `servers` URL in the spec, with no auth.

When the MCP server runs over HTTP, FastMCP also copies the headers of the incoming MCP request onto the upstream request (not `authorization` or `cookie`, and never over a header you set on the client). A request hook can strip the rest.

::right::

```py
client = httpx2.AsyncClient(
    base_url="https://api.example.com",
    # example only
    headers={"Authorization": "Bearer ..."},
)

mcp = FastMCP.from_openapi(
    spec,
    client=client,
    name="Example",
)

mcp.run()
```

---

# How a route can be exposed

Each operation becomes one of four things.

| Type | Who uses it, and how | Typical route |
|---|---|---|
| `TOOL` | the model calls it with arguments | POST, PUT, DELETE, and GETs that take arguments |
| `RESOURCE` | the client reads it by URI, no arguments | a GET with no parameters |
| `RESOURCE_TEMPLATE` | the client reads it by URI, with path parameters in the URI | a GET like `/items/{id}` |
| `EXCLUDE` | nobody, it is hidden | internal or admin routes |

A resource is data the client reads on its own, for example to attach as context. A tool is something the model decides to call. A resource template carries path parameters only.

---

# Choose what to expose, and how

```py
def demote_resources_with_args(route, mcp_type):
    if mcp_type == MCPType.RESOURCE and route.parameters:
        return MCPType.TOOL  # a resource cannot take arguments
    return mcp_type

mcp = FastMCP.from_openapi(
    spec, client=client,
    route_maps=[
        RouteMap(pattern=r"^/admin", mcp_type=MCPType.EXCLUDE),  # hide admin routes
        RouteMap(methods=["GET"], mcp_type=MCPType.RESOURCE),    # every other GET: resource
    ],
    route_map_fn=demote_resources_with_args,  # then fix the exceptions
)
```

`route_maps` are rules on method and path. The first matching rule wins, and a route that matches none (a POST here) stays a tool, the default. `route_map_fn` then runs on each route with the type the rules picked and can change it, here keeping GETs that take arguments as tools. Use either one alone, or both.

<!--
Also available: mcp_names renames tools (operationId to name), and mcp_component_fn edits each component after it is built, for example to add annotations.
Caveats: an exception inside route_map_fn is logged as a warning and swallowed, so the rule's type stays. route_map_fn also sees EXCLUDE routes and could un-exclude them.
-->

---
class: dense
---

# Transform a tool

A generated tool mirrors the API. A transform reshapes it for an LLM.

```py
from fastmcp.tools.tool_transform import ArgTransform, TransformedTool, forward_raw

generated = await mcp.get_tool("listItems")  # tool name: the operationId, slugified
async def recent_items(days: int = 30):  # the arguments the LLM will see
    start = date.today() - timedelta(days=days)
    return await forward_raw(startDate=start.isoformat())  # original API argument names

mcp.disable(names={"listItems"}, components={"tool"})  # else the LLM sees both versions
mcp.add_tool(TransformedTool.from_tool(
    generated,
    name="recent_items",
    description="Items from the last N days.",  # without it, the spec's description is kept
    transform_fn=recent_items,
    transform_args={"startDate": ArgTransform(hide=True), "limit": ArgTransform(hide=True)},
))
```

`ArgTransform` renames, redescribes, sets a default for, or hides an argument. A hidden argument must be optional in the spec or get a `default=`. `forward_raw` calls the original tool with its own names (next slide).

---
class: dense
---

# Calling the underlying API

| Call | Argument names | Use it for |
|---|---|---|
| `forward(...)` | the new ones | passing on what the LLM sent |
| `forward_raw(...)` | the original API ones | setting arguments the LLM does not see |
| `client.get(...)` | plain HTTP | endpoints missing from the spec |
| `tool.run({...})` | the tool's own | calling another registered tool |

```py
await forward_raw(startDate="2026-01-01")
await client.get("/items", params={"limit": 1})  # same base URL, auth and hooks
tool = await mcp.get_tool("recent_items")        # then: await tool.run({"days": 7})
```

`forward`, `forward_raw` and `tool.run` return a `ToolResult` (response in `.structured_content`). `client.get` returns a plain `httpx2.Response`: call `raise_for_status()` yourself.

---
class: dense
---

# forward or forward_raw?

Both call the generated tool from inside your function. They differ in whose argument names you use. Say the transform renames `startDate` to `since` and hides `limit` with `default=10`.

| You call | The API receives |
|---|---|
| `forward(since=...)` | `startDate` and `limit=10` |
| `forward_raw(startDate=...)` | `startDate` only |
| `forward_raw(startDate=..., limit=5)` | `startDate` and `limit=5` |
| `forward(since=..., limit=5)` | `TypeError`, `limit` is hidden |
| `forward_raw(since=...)` | nothing: the unknown name is dropped silently |

`forward` uses the new tool's names, applies renames and hidden defaults, and validates. `forward_raw` uses the original API's names and applies nothing, so it is how you set a hidden argument to your own value, and a wrong name fails silently.

---
layout: section
class: tiingo
---

# Part 2
## Applied to Tiingo

Tiingo is a financial research platform. The API we use serves prices, fundamentals, crypto and FX data.

tiingo.com · api.tiingo.com/documentation

---
class: tiingo dense
---

# The setup

The only spec is a community one (`api-evangelist/tiingo`), so we vendor it and patch it. This is `create_server`, trimmed.

```py
client = httpx2.AsyncClient(
    base_url=str(settings.tiingo_api_url).rstrip("/"),
    follow_redirects=True,  # /iex answers 301 to /iex/
    event_hooks={"request": [strip_forwarded_headers]},  # only allow-listed headers go to Tiingo
    headers={"Authorization": f"Token {api_key}"},
)
mcp = FastMCP.from_openapi(
    openapi_spec=SPEC,  # the vendored, patched YAML, read with yaml.safe_load
    client=client,
    route_map_fn=route_map_fn,  # the allow-list, next slide
    mcp_names=MCP_NAMES,  # operationId to tool name: getDailyPrices becomes daily_prices
    mcp_component_fn=annotate_component,  # flags GET tools as read-only, a hint to clients
)
```

<!--
The header allow-list includes authorization. That is safe only because the client's own Token header is already set and FastMCP does not overwrite it.
The startup check on EXPOSED is a plain assert, which python -O removes.
-->

---
layout: two-cols
layoutClass: tiingo
---

# Expose: an allow-list

`route_map_fn` looks each operationId up and excludes the rest.

12 operations are generated as tools and 1 as a resource. `mcp_component_fn` flags the tools read&#8209;only, a hint to clients.

A new operation in a refreshed spec stays hidden until someone adds it, and a startup assert fails if an allowed id is missing from the spec.

::right::

```py
EXPOSED: dict[str, MCPType] = {
    **dict.fromkeys(
        [
            "testConnection",
            "searchAssets",
            "getDailyPrices",
            # ...12 in total
        ],
        MCPType.TOOL,
    ),
    **dict.fromkeys(
        ["getFundamentalsDefinitions"],
        MCPType.RESOURCE,
    ),
}

def route_map_fn(route, _default):
    return EXPOSED.get(
        route.operation_id or "", MCPType.EXCLUDE
    )
```

---
class: tiingo
---

# The spec is wrong in places

We called every tool against the live API and compared. FastMCP builds each tool's output schema from the spec, so a response that does not match is rejected by the client until the spec is patched.

| Where | The spec says | The API returns |
|---|---|---|
| `CryptoPrices.priceData` | one object | an array of objects |
| `IexTopOfBook` quote fields | never null | null outside market hours |
| a fundamentals statement section | one pair | a list of pairs |
| `DailyMeta` dates | never null | null when there is no price data |

---
class: tiingo
---

# Some tools return too much

Generated tools pass the vendor payload through untouched, and the whole response lands in the LLM's context. A big payload costs tokens and buries the answer, and the vendor's arguments, like start and end dates, are left to the model to fill in.

<div class="cards">
  <div class="card">
    <h3>Generated</h3>
    <code>getDailyPrices</code> takes start and end dates and returns Tiingo's full payload for the whole range. <code>getDistributionYield</code>, which we did not expose, would return about 780 KB (11k rows) and takes only a ticker.
  </div>
  <div class="card">
    <h3>Wrapped</h3>
    <code>recent_daily_prices</code>, <code>recent_financials</code> and <code>recent_valuation_metrics</code> take <code>lookback_days</code> or <code>periods</code>, keep seven fields per price bar and validate their bounds.
  </div>
</div>

The fix is a wrapper that takes arguments the model can fill in easily and trims what comes back. Pydantic models generated from the spec give the wrapped tools a typed output schema.

---
class: tiingo dense
---

# The wrapper

The Part 1 transform, with the docstring as the description.

```py
@validate_call  # checks lookback_days is 1 to 366
async def recent_daily_prices(ticker: str, lookback_days: LookbackDays = 30) -> list[DailyPriceBar]:
    """End-of-day OHLCV prices over the last `lookback_days` calendar days."""
    start = date.today() - timedelta(days=lookback_days)
    rows = await forward_rows(ticker=ticker, startDate=start.isoformat())  # runs the generated getDailyPrices
    return [DailyPriceBar.model_validate(r) for r in rows]  # keeps 7 fields, drops the rest
```

`wrap_tool` and `forward_rows` are our helpers in `tools/wrap.py`. `wrap_tool` hides every argument the function does not declare and swaps the tool in.

`forward_rows` wraps `forward_raw` and returns the list payload. The wrapper still calls the generated tool, so the request is still built from the spec.

---
class: tiingo
---

# A tool with its own UI

Some answers are better as a picture. `plot_cumulative_returns` compares 1 to 5 tickers: the model gets a text summary, and a host that supports MCP Apps also shows a line chart.

<div class="pipeline flow">
  <div class="col"><div class="step"><b>The model calls it</b><small>1 to 5 tickers, a lookback</small></div></div>
  <div class="col"><div class="step"><b>Fetch prices</b><small>recent_daily_prices per ticker</small></div></div>
  <div class="col"><div class="step"><b>Compute returns</b><small>adjusted close, % since the first day</small></div></div>
  <div class="col"><div class="step"><b>Return two things</b><small>a text summary and the chart data</small></div></div>
  <div class="col"><div class="step"><b>The host draws it</b><small>a line chart, from the widget</small></div></div>
</div>

<div class="cards one">
  <div class="card">
    <h3>Demo</h3>
    In the MCP Inspector, open the Apps tab and run <code>plot_cumulative_returns</code> with 2 to 3 tickers and a 90-day lookback.
  </div>
</div>

<!--
Demo steps:
1. uv run tiingo-mcp (TIINGO_API_KEY set, MCP_AUTH_MODE=none)
2. npx @modelcontextprotocol/inspector, Streamable HTTP, http://localhost:8741/mcp
3. Apps tab, run plot_cumulative_returns with 2 to 3 tickers
4. Show the same call in a client without MCP Apps: text summary only
Fallback if the API is down: show the tests (uv run pytest), they use a mocked transport.
Registration order matters: the wrappers are registered first, then the chart tool, which looks up recent_daily_prices with require_tool and fails at startup if it is missing.
-->

---
class: tiingo dense
---

# How the chart tool is wired

```py
@mcp.tool(
    name="plot_cumulative_returns",
    app=AppConfig(resource_uri="ui://tiingo/returns.html"),  # links the tool to its widget
)
async def plot_cumulative_returns(tickers: Tickers, lookback_days: LookbackDays = 90) -> ToolResult:
    ...  # per ticker: recent_daily_prices, then the percent return since the first day
    return ToolResult(
        content=text,  # for the model, e.g. "Cumulative return ...: AAA +4.20%, BBB -1.10%."
        structured_content=chart.model_dump(mode="json"),  # data for the widget
    )

@mcp.resource("ui://tiingo/returns.html", app=AppConfig(prefers_border=True))
def widget() -> str:
    return WIDGET_PATH.read_text()  # one HTML file that draws the chart
```

The tool and the widget are linked by the `ui://` URI. The widget is a single HTML file: it talks to the host over `postMessage` (MCP Apps), receives the structured data, and draws a line chart with a Chart and Table toggle. The text summary is always returned, so a client without MCP Apps support still has it.

---
class: tiingo
---

# Not covered

| Area | State |
|---|---|
| OAuth storage | in memory, so sessions end with the process |
| Deploy files | target the product repo, not run |
| Zitadel login | mocked discovery only |
| Chart | checked in the MCP Inspector only |
| Plan limits | on our plan, 403 on news, splits, distributions and fund fees. Fundamentals: Dow 30 only |
