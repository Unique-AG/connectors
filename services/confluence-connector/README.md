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
docker compose -f local-confluence-v8.5-docker-compose.yaml up -d
```

- Starts Confluence 8.5 on http://localhost:8090, user `admin`, password `CONFLUENCE_PASSWORD_LOCAL_DC` from `.env`.
- The `seed` service sets it up with Atlassian's 3-hour [timebomb license](https://developer.atlassian.com/platform/marketplace/timebomb-licenses-for-testing-server-apps/) and creates the space `TEST`: labeled pages, child pages and attachments, plus one page that must not be ingested.
- The license runs out after 3 hours. Run the same command again to renew it. Existing content is kept.
- Point a tenant config at it with `instanceType: data-center`, `baseUrl: http://localhost:8090` and `auth.mode: basic`.

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
