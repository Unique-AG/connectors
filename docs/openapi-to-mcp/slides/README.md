# OpenAPI to MCP deck

A Slidev deck for UN-27321: how FastMCP turns an OpenAPI spec into an MCP server, applied to the experimental Tiingo MCP.

```sh
bun install
bun run dev      # http://localhost:3030
```

With pnpm, run `pnpm install --ignore-workspace` so the repo's root lockfile stays untouched.

To export a PDF, install a Chromium once, then run the export:

```sh
bunx playwright install chromium
bun run export   # writes openapi-to-mcp.pdf
```

Other formats: `bunx slidev export --format pptx` for PowerPoint, or `--format png` for one image per slide.
