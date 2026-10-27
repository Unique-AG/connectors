# Shared

[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

`shared/` is the layer below `upstream` and `persistence`, above only `telemetry`. Every other
layer may import it, and it imports none of them. It is where something lives when more than one
layer needs it, so that neither layer has to import the other to get it.

```
shared/
├── __init__.py      # every name the other layers import, and nothing else
├── contracts/       # types two layers agree on
└── utils/           # helpers more than one layer calls
```

Both start empty. Something moves here when a second layer needs it, not before: what one layer
uses stays in that layer.

## Contracts

`upstream` and `persistence` sit side by side and cannot import each other, and `mcp` must not
be the only place two lower layers can meet. A contract is the agreement between them, written
down once where both can reach it:

- a protocol one layer implements and another calls, such as `AuthStore`, which `persistence`
  implements and `mcp/auth` uses without knowing it is SQL;
- a value model that crosses the boundary, such as `UpstreamCredentials`, which `persistence`
  stores and `upstream` signs its requests with;
- a type alias for a function one layer hands another, such as `CredentialsProvider`.

A contract is types only. What implements it lives in the layer that owns the work: the SQL
store in `persistence/`, how a request is signed in `upstream/`. import-linter keeps
`sqlalchemy`, `httpx2` and `cryptography` out of `shared/contracts/`, and keeps `fastmcp`, `mcp`
and `mcp_types` out of all of `shared/`. A contract may use pydantic and the standard library.

Group the contracts of one concern in one module, `contracts/auth.py` for the sign-in, and
export them from `contracts/__init__.py` and `shared/__init__.py`. A layer imports them from the
top: `from <package>.shared import AuthStore`.

`mcp-scaffold <name> ... --auth credentials` writes the first one. [`auth.md`](auth.md) shows how
the layers use it.

## Utils

A helper is code more than one layer calls and that belongs to none of them, such as a formatter
or a date rule. Like a contract, it imports nothing from a layer above and nothing from MCP. A
helper that holds a rule of the domain is not a helper: it belongs to the feature in `contexts/`
that owns the rule.
