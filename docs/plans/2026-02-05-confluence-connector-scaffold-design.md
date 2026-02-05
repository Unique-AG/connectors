# Design: Confluence Connector v2 Project Scaffold

**Ticket:** UN-16932

## Problem

We need to create the foundation for Confluence Connector v2 in the connectors repository. This includes:
- NestJS project structure following SharePoint Connector v2 patterns
- Basic Helm chart for early deployment
- CI/CD workflows for validation and deployment
- Placeholder configuration for future Confluence integration

The goal is to have a deployable unit today that can be iterated on in subsequent tickets.

## Solution

### Overview

Create a minimal but fully deployable NestJS service by adapting the SharePoint Connector v2 structure. The service will include:

1. **NestJS application scaffold** with health endpoint
2. **Placeholder Confluence configuration** (to be filled in future tickets)
3. **Unique API configuration** (copied from SharePoint - same integration pattern)
4. **Helm chart** with alerts and Grafana dashboard support (no proxy config)
5. **CI/CD workflows** for automated testing and deployment

### Architecture

```
services/confluence-connector/
├── .env.example
├── .swcrc
├── nest-cli.json
├── package.json
├── tsconfig.json
├── tsconfig.build.json
├── turbo.json
├── vitest.config.ts
├── deploy/
│   ├── Dockerfile
│   └── helm-charts/
│       └── confluence-connector/
│           ├── Chart.yaml
│           ├── values.yaml
│           ├── values.schema.json
│           ├── templates/
│           │   ├── _helpers.tpl
│           │   ├── tenant-config.yaml
│           │   ├── grafana-dashboard.yaml
│           │   └── alerts/
│           │       └── unique-api.yaml
│           └── files/
│               └── grafana-dashboard.json
├── src/
│   ├── main.ts
│   ├── app.module.ts
│   └── config/
│       ├── index.ts
│       ├── app.config.ts
│       ├── confluence.schema.ts (placeholder)
│       └── unique.schema.ts (from SharePoint)
└── test/
    └── setup.ts
```

**Key Components:**

1. **main.ts**: Bootstrap with OpenTelemetry instrumentation
2. **app.module.ts**: ConfigModule, LoggerModule, ProbeModule, OpenTelemetryModule
3. **config/**: Zod schemas for type-safe configuration
4. **Helm chart**: Uses `backend-service` dependency, includes Grafana/alerts

**Ports:**
- Application: 51347
- Metrics: 51348

### Configuration

**App Config** (`app.config.ts`):
- `port`: 51347
- `logLevel`: configurable log level
- `environment`: NODE_ENV

**Unique Config** (`unique.schema.ts` - copied from SharePoint):
- `serviceAuthMode`: `cluster_local` | `external`
- For `cluster_local`: `serviceExtraHeaders` (x-company-id, x-user-id)
- For `external`: Zitadel OAuth config
- `ingestionServiceBaseUrl`: Unique ingestion service
- `scopeManagementServiceBaseUrl`: Unique scope management
- `apiRateLimitPerMinute`: Rate limiting
- `ingestionConfig`: Optional ingestion settings

**Confluence Config** (`confluence.schema.ts` - placeholder):
- `instanceType`: `cloud` | `onprem`
- `baseUrl`: Confluence instance URL
- `auth`: Placeholder for authentication (cloud OAuth or on-prem PAT)
- `apiRateLimitPerMinute`: Rate limiting
- `ingestSingleLabel`: Label for single-page sync
- `ingestAllLabel`: Label for full sync

### CI/CD Workflows

**CI Workflow** (`confluence-connector.ci.yaml`):
- Uses template `_template-ci.yaml` with `orm: none`
- Runs on PRs touching `services/confluence-connector/**`
- Validates: lint, type-check, build, test
- Chart validation: helm template, helm-docs, ct lint

**Cache Workflow** (`confluence-connector.cache.yaml`):
- Docker layer caching for faster builds

**CD Workflow** (`confluence-connector.dispatch.yaml`):
- Triggered by release-please on version bumps
- Uses template `_template-cd.yaml`
- Builds container, pushes to GHCR and ACR
- Packages and pushes Helm chart

### Error Handling

Standard NestJS exception handling with:
- Pino structured logging
- OpenTelemetry tracing
- Prometheus metrics

### Testing Strategy

- `test/setup.ts`: Mock environment, silence logs
- `vitest.config.ts`: Standard config extending root
- No business logic tests in scaffold (added with features)
- CI runs `pnpm test` which passes with minimal setup

## Out of Scope

- Confluence API integration (future ticket)
- Sync/scheduler logic (future ticket)
- Database/ORM (not needed for this connector)
- Terraform modules for Azure AD (future ticket)
- Proxy configuration (not applicable to Confluence)
- Full Grafana dashboard content (placeholder for now)

## Tasks

1. **Create NestJS project structure** - Copy SharePoint connector structure, rename to confluence-connector, strip business logic modules, keep only skeleton (app.module, main.ts, config).

2. **Set up configuration schemas** - Create app.config.ts with port/logLevel, copy unique.schema.ts from SharePoint, create placeholder confluence.schema.ts with instanceType, baseUrl, auth placeholder, labels.

3. **Set up test infrastructure** - Create test/setup.ts with mocked env vars, create vitest.config.ts extending root config.

4. **Create Helm chart** - Copy SharePoint helm-charts structure, adapt values.yaml (no proxy config), include Grafana dashboard placeholder, include Unique API alerts.

5. **Create CI workflow** - Create confluence-connector.ci.yaml using template with orm: none, include chart validation job.

6. **Create CD workflow** - Create confluence-connector.cache.yaml and confluence-connector.dispatch.yaml using templates.

7. **Verify build and deployment** - Run pnpm build, pnpm test, helm template to verify everything works.
