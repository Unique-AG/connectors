# deploy

- `deploy/Dockerfile` builds from the repository root, so it can copy a shared package from
  `packages/` that `[tool.uv.sources]` points at. Add a `COPY` line for every new one the MCP
  runs with; a dev-only one, such as `mcp-architecture`, stays out of the image.
- `deploy/helm-charts/<name>/` is a thin chart over the shared `base` chart. `values.yaml` holds
  the portable defaults. The hostname, `MCP_BASE_URL` and the secrets are set per deployment in
  the Argo overlay.
- `values.schema.json` is generated: after changing `values.additional.schema.json`, run
  `scripts/render-values-schema.sh` from the repository root.
- A new env variable goes in `.env.example`, and in `values.yaml` under `env` unless it is a
  secret.
- release-please bumps the versions in `pyproject.toml`, `uv.lock`, `Chart.yaml` and the image
  tag in `values.yaml`. Never bump them by hand.
