# Confluence Connector

Take content from Confluence and send it to Unique AI for RAG ingestion.

## Development

```bash
cp .env.example .env
pnpm install
pnpm dev
```

### Local Confluence Data Center

Run these from `services/confluence-connector`.

Before you start, create `.env` (`cp .env.example .env`) and check these variables:

| Variable | Where | Value |
|---|---|---|
| `TENANT_CONFIG_PATH_PATTERN` | `.env` | `src/tenant-configs/*-tenant-config.yaml` (the default `/app/...` path is for the container) |
| `CONFLUENCE_PASSWORD_LOCAL_DC` | `.env` | `admin`. Used by the Confluence setup and by the tenant config |
| `ZITADEL_CLIENT_SECRET` | `.env` | the client secret of the `confluence-connector` service user, from step 4.2 |
| `FEATURE_FLAG_ENABLE_SERVICE_USER_API_KEY_UN_22696` | monorepo, `next/services/node-scope-management/app.env` | `true`, see step 4.1 |
| `CONFLUENCE_LICENSE_KEY` | optional, `-e` on the seed command | a license key, to skip the prompt (step 6) |

0. Optional: delete an old local Confluence and all its data, to start clean. Your Unique data is not touched, and the connector keeps its root scope because the server ID is pinned.

   ```bash
   docker compose -f local-confluence-v8.5-docker-compose.yaml down -v
   ```

1. Start Confluence and set it up:

   ```bash
   docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm seed
   ```

2. When it asks for a license key (after about 3 minutes on the first start), either:
   - paste a free 30-day trial key from the printed link, then press Enter on an empty line, or
   - press Enter to use Atlassian's 3-hour [timebomb license](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/).
3. Wait for `[seed] done`. Confluence runs on http://localhost:8090, user `admin`, password `admin` (or `CONFLUENCE_PASSWORD_LOCAL_DC` from `.env`). The space `TEST` holds labeled pages, child pages, attachments, and one page that must not be ingested.
4. Once per machine, prepare your local Unique for the connector:
   1. In the monorepo, set `FEATURE_FLAG_ENABLE_SERVICE_USER_API_KEY_UN_22696=true` in `next/services/node-scope-management/app.env` and restart scope management. Without it, scope management ignores the service user from the next step, its roles never reach Gatekeeper, and every call fails with `Forbidden resource`.
   2. In your local Zitadel (http://localhost:10116/ui/console), create the service user `confluence-connector` and generate a client secret. Put the secret in `.env` as `ZITADEL_CLIENT_SECRET`.
   3. Give that user `chat.admin.all`, `chat.knowledge.read` and `chat.knowledge.write` on the **Unique Apps** project, and note the project ID.
   4. Create an empty folder in your local Unique knowledge base, and note its scope ID.
   5. Copy [`examples/data-center-local-basic-auth.yaml`](./src/tenant-configs/examples/data-center-local-basic-auth.yaml) to `src/tenant-configs/local-dc-tenant-config.yaml`, and fill in `zitadelProjectId` and `scopeId`.
5. Run `pnpm dev`. The first sync of `local-dc` should report 8 new items: 5 pages and 3 attachments.
6. To update the license later, run step 1 again and paste the new key. To skip the prompt, pass the key:

   ```bash
   docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm \
     -e CONFLUENCE_LICENSE_KEY="<key>" seed
   ```

   Content is kept. Stop Confluence with `docker compose -f local-confluence-v8.5-docker-compose.yaml down`.

> [!NOTE]
> **About the license**
>
> - **Timebomb (press Enter):** the same public key works every time. Each time it is applied, it is valid for 3 hours. When it runs out, repeat step 1 and press Enter.> - **30-day trial (paste a key):** better for longer sessions. The compose file pins the server ID (`ATL_PRODUCT_SERVER_ID`), so the key also works after `down -v`.
> - **Pasted keys are kept.** Pressing Enter never replaces a pasted key with the timebomb key.

## Configuration

The connector uses YAML-based tenant configuration files. See [`src/tenant-configs/`](./src/tenant-configs/) for the local dev config and [`src/tenant-configs/examples/`](./src/tenant-configs/examples/) for reference configurations.

Environment variables and secrets are documented in [`.env.example`](./.env.example).

## Scripts

| Command | Description |
|---------|-------------|
| `pnpm dev` | Start in development mode |
| `pnpm build` | Production build |
| `pnpm test` | Run unit tests |
| `pnpm test:watch` | Run tests in watch mode |
| `pnpm test:coverage` | Coverage report |
| `pnpm check-all` | Lint + type check |
