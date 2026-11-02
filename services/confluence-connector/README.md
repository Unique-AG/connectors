# Confluence Connector

Take content from Confluence and send it to Unique AI for RAG ingestion.

## Development

```bash
cp .env.example .env
pnpm install
pnpm dev
```

### Local Confluence Data Center

Run everything from `services/confluence-connector`.

#### Start Confluence

```bash
# Optional: delete the old local Confluence and its data. Unique data is not touched.
docker compose -f local-confluence-v8.5-docker-compose.yaml down -v

docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm seed
```

1. At the license prompt (about 3 minutes on the first start), paste a free 30-day trial key from the printed link and press Enter on an empty line. Or just press Enter for Atlassian's 3-hour [timebomb license](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/).
2. Wait for `[seed] done`. Confluence runs on http://localhost:8090 (`admin` / `admin`), with a `TEST` space: labeled pages, child pages, attachments, and one page that must not be ingested. Each one holds a fact you can ask Unique about. The tree is at the top of [`local-confluence/seed.py`](./local-confluence/seed.py).

Stop it with `docker compose -f local-confluence-v8.5-docker-compose.yaml down`.

#### Connect the connector (once per machine)

1. In the monorepo, set `FEATURE_FLAG_ENABLE_SERVICE_USER_API_KEY_UN_22696=true` in `next/services/node-scope-management/app.env`, and restart scope management. Without it, the service user's roles never reach Gatekeeper, and every call fails with `Forbidden resource`.
2. In your local Zitadel (http://localhost:10116/ui/console), create the service user `confluence-connector` with a client secret. Give it `chat.admin.all`, `chat.knowledge.read` and `chat.knowledge.write` on the **Unique Apps** project.
3. Create an empty folder in your local Unique knowledge base.
4. Copy [`examples/data-center-local-basic-auth.yaml`](./src/tenant-configs/examples/data-center-local-basic-auth.yaml) to `src/tenant-configs/local-dc-tenant-config.yaml`. Fill in the project ID and the folder's scope ID.
5. In `.env`, set:
   - `TENANT_CONFIG_PATH_PATTERN=src/tenant-configs/*-tenant-config.yaml`
   - `ZITADEL_CLIENT_SECRET=` the secret from step 2
   - `CONFLUENCE_PASSWORD_LOCAL_DC=admin` (already in `.env.example`)
6. Run `pnpm dev`. The first sync of `local-dc` should report 8 new items: 5 pages and 3 attachments.

#### License

- **Timebomb:** the same public key works every time, for 3 hours from when it is applied. When it runs out, run the seed command again and press Enter.
- **30-day trial:** better for longer sessions. The server ID is pinned (`ATL_PRODUCT_SERVER_ID`), so the key, and the connector's root scope, survive `down -v`.
- **Change the key** by running the seed command again, or without the prompt:

  ```bash
  docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm -e CONFLUENCE_LICENSE_KEY="<key>" seed
  ```

  Content is kept, and pressing Enter never replaces a pasted key.

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
