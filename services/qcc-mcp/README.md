# qcc-mcp

A [FastMCP](https://github.com/jlowin/fastmcp) connector for the **QCC
(Qichacha International) KYC/KYB gateway** — CN company registry data and
**Ultimate Beneficial Owner** lookups.

> **Status: local prototype — not deployed.** Modeled on `office-365-mcp`, but
> with the OAuth/Postgres/OTel layers stripped: QCC authenticates with a static
> API-key signature, so the whole thing is *config → client → tools*. The client
> is a port of the proven `qcc-connector-skill/qcc.py`.

## Tools

| Tool | Purpose |
|---|---|
| `qcc_search` | resolve a company name/BRN → `qccCode` (do this first) |
| `qcc_search_person` | resolve a person + company → `personKeyNo` |
| `qcc_company_basic` | full KYC Basic report (profile, capital, shareholders, officers, branches) |
| `qcc_ubo_report` | full report **+ UBO ownership chain** + subsidiaries/affiliates |
| `qcc_executive_report` | report for an individual |
| `qcc_submit_ubo_order` | submit an order, get an `order_no` (for drilling) |
| `qcc_get_section` | read one section by `order_no`: profile, capital, shareholders, officers, branches, subsidiaries, affiliates, ubo (shareholders/officers paginate) |

## Auth

Every call carries three headers — `ApiKey`, `Timespan` (unix seconds), and
`Token = MD5(ApiKey + Timespan + SecretKey)` uppercased. The secret is never
transmitted. Reports are compiled asynchronously; the tools submit an order and
poll (`status 204` = still processing) until ready.

## Run locally

```bash
cd services/qcc-mcp
uv sync                       # or: pip install -e .
cp .env.example .env          # fill in QCC_API_KEY / QCC_SECRET_KEY (sandbox to start)
qcc-mcp                       # stdio transport (what an MCP client spawns)
# or over HTTP:
QCC_MCP_HTTP=1 qcc-mcp
```

Point any MCP client at it (stdio: run `qcc-mcp`; HTTP: `http://127.0.0.1:8000`).

## Not included (deploy-day, out of scope for the prototype)

- Kubernetes/Helm manifests, gitops
- Secrets from the platform store (here: `.env` / env vars)
- Adding `gateway.qcckyc.com` to the sandbox **egress allowlist** (default-deny)
- OpenTelemetry / metrics / readiness endpoints

## Scope

CN mainland entities only. A Cayman/HK parent (e.g. Tencent Holdings) is a
different jurisdiction and not covered by these endpoints. In `qcc_ubo_report`,
`subsidiaries`/`affiliates` are what the company **owns**, not its owners.
