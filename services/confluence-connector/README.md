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

1. Start Confluence and set it up:

   ```bash
   docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm seed
   ```

2. When it asks for a license key (after about 3 minutes on the first start), either:
   - paste a free 30-day trial key from the printed link, then press Enter on an empty line, or
   - press Enter to use Atlassian's 3-hour [timebomb license](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/).
3. Wait for `[seed] done`. Confluence runs on http://localhost:8090, user `admin`, password `admin` (or `CONFLUENCE_PASSWORD_LOCAL_DC` from `.env`). The space `TEST` holds labeled pages, child pages, attachments, and one page that must not be ingested.
4. Copy [`examples/data-center-local-basic-auth.yaml`](./src/tenant-configs/examples/data-center-local-basic-auth.yaml) to `src/tenant-configs/`, fill it in, and run `pnpm dev`. The example lists the one-time setup in your local Unique.
5. To update the license later, run step 1 again and paste the new key. To skip the prompt, pass the key:

   ```bash
   docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm \
     -e CONFLUENCE_LICENSE_KEY="<key>" seed
   ```

   Content is kept. Stop Confluence with `docker compose -f local-confluence-v8.5-docker-compose.yaml down`. Add `-v` to delete all its data.

> [!NOTE]
> **About the license**
>
> - **Timebomb (press Enter):** the same public key works every time. Each time it is applied, it is valid for 3 hours. When it runs out, repeat step 1 and press Enter.
> - **30-day trial (paste a key):** better for longer sessions. The compose file pins the server ID (`ATL_PRODUCT_SERVER_ID`), so the key also works after `down -v`.
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
