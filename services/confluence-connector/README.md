# Confluence Connector

Take content from Confluence and send it to Unique AI for RAG ingestion.

## Development

```bash
cp .env.example .env
pnpm install
pnpm dev
```

### Local Confluence Data Center

```bash
docker compose -f local-confluence-v8.5-docker-compose.yaml run --rm seed
```

- Starts Confluence 8.5 on http://localhost:8090, user `admin`, password `CONFLUENCE_PASSWORD_LOCAL_DC` from `.env` (default `admin`).
- Asks for a license key and prints the link to get a free 30-day trial key. Press Enter instead to use Atlassian's 3-hour [timebomb license](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/).
- Creates the space `TEST`: labeled pages, child pages and attachments, plus one page that must not be ingested.
- Run it again for a new license. Existing content is kept. `up -d` also works, and renews only the timebomb license.
- For the tenant config, start from [`examples/data-center-local-basic-auth.yaml`](./src/tenant-configs/examples/data-center-local-basic-auth.yaml). It lists the one-time setup in your local Unique.

> [!NOTE]
> **About the license**
>
> - **Timebomb (press Enter):** the same public key works every time. Each time it is applied, it is valid for 3 hours. When it runs out, run the command again and press Enter.
> - **30-day trial (paste a key):** better for longer sessions. The compose file pins the server ID (`ATL_PRODUCT_SERVER_ID`), so the key also works after `down -v`.
> - **Pasted keys are kept.** Running the command again never replaces a pasted key with the timebomb key.

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
