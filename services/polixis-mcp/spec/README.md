# Polixis's spec, and what we change in it

| File | |
|---|---|
| `polixis-graph.openapi.json` | Polixis's own spec for the graph service, polixis-graph 0.26.10.23.1, exactly as they sent it. Never edit it: it is the record of what they gave us |
| `merge_spec.py` | Every change we make to it, one `Edit` each |
| `../src/polixis_mcp/upstream/openapi.yml` | What `uv run poe merge-spec` builds from the two, and what the codegen reads. Never edit it by hand |

Their spec is the source of truth. The merge adds what it lacks and corrects only what the live
API contradicted when we probed it in November 2026. Each change also says why in the
description it writes into `openapi.yml`, so the reason travels with the spec.

## How the merge works

`merge_spec.py` keeps one function per section below. Each returns a list of `Edit`s, a path
of keys into the spec and what to do there:

- `set_` puts a value there, adding it when missing, such as a schema of our own;
- `append` adds text to the end of their description;
- `update` adds keys to one of their objects;
- `extend` adds items to one of their lists.

`merge` applies them in order to a copy of their spec and never changes theirs. An `append`,
`update` or `extend` whose target their spec no longer has fails with the path, so a renamed
schema or field shows up when you run the merge, not later in the codegen.

## What we change, and why

| Section | Change | Why |
|---|---|---|
| `_service` | OpenAPI 3.0.3 | Our codegen reads 3.0 only; their 3.1.0 file uses nothing 3.0 lacks |
| | Server `https://api-polixis.polixis.com` | Their spec gives a `/graph` prefix the API does not answer on |
| | Security: OAuth2 client credentials and the `x-api-key` header | Their spec declares neither |
| | Tags `Search` and `Undocumented` | For the operations we add |
| `_operation_ids` | An operationId on each operation | Theirs has none, and the codegen names each operation after its id |
| `_rejections` | `error` and `code` on the responses of every endpoint that takes an id, and the `RejectionMessage` and `RejectionCode` schemas | An id Polixis does not know gets a 200 with that body in place of the response; the client's `response_check` turns it into a `PolixisRejectedError` on every call |
| `_timestamps` | `at`, `startDate` and `endDate` described as epoch seconds | Their spec says milliseconds; every live value was in seconds |
| | Direction of an edge | The source holds each detail's role in the target |
| `_corporate` | `page` required on the corporate profile, with its flat response | Without `page` the response takes another shape; the tools use the flat one |
| | `category` required | A request without it gets a 500 |
| | Relation type names and the shape of `flags` | The live API sends names and a shape their spec does not give |
| `_graph` | `NodeMeta` and `NodeMetaMap` typed, and used as the graphs' and trees' `meta` | Their spec leaves `meta` a free-form object |
| | Notes on `alertNames`, `flags`, `allowedCtg`, `excludedCtg`, `sharePercent` and `totalNodes` | What the live values look like, and what is still unconfirmed |
| | The ownership caps, and what the smart graph leaves out | From their PDF |
| `_completion` | The completion response typed as `Profile`, with `SanctionRecord` and `Position` | Their spec leaves it a free-form object |
| `_names` | The live values of a name record's `type` | |
| `_permanent_id` | The pid statuses, and the 400, 410 and 500 responses | Seen live, and the 410 from their PDF |
| | The operation's description, written for an agent | It is served as the `resolve_permanent_id` tool, and theirs describes the HTTP answers, not when to call it |
| | The `pid` parameter's pattern | Shows the agent what a pid looks like. FastMCP does not check a tool served from the spec against it, so a malformed pid still reaches Polixis |
| `_search` | The whole search service, `POST /search/api`, and its schemas | Their spec covers only the graph service; written from their PDF and live responses |
| `_undocumented` | `/api/sanction/{id}`, `/api/graph/path`, `/api/judicial/{id}` and `/api/search` under the `Undocumented` tag, typed from live responses | The live API answers them but their spec leaves them out. Whether Polixis supports them is an open question to them |
| `_wrap_annotated_refs` | A `$ref` with a description beside it moves into `allOf` | OpenAPI 3.0 ignores a `$ref`'s siblings, and the codegen would not follow it |

Every response field stays optional, as in their spec.

Two things the live API showed that no edit can express: the full subgraph never carries
names, even when `fields` asks for them, so the tools take them from the smart graph's `meta`;
and both graph endpoints stopped at two hops in every walk we tried, whatever the `radius`.

## When Polixis sends a new spec

1. Replace `polixis-graph.openapi.json` with their file, unchanged. `git diff` on it shows what
   they changed.
2. Run `uv run poe merge-spec`. An edit whose target they removed or renamed fails with its
   path: fix or drop it. Drop the edits their spec now covers, such as a correction they made.
3. Run `uv run poe codegen`.
4. `uv run poe typecheck` names every place a changed model breaks. The contexts map every
   vendor model, so fix the mapping there and the tools keep their shape.
5. `uv run poe architecture` shows how `resolve_permanent_id`'s arguments and output changed.
   Read the diff, then accept it with `uv run poe surface`.
