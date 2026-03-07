# INFRA-001: Monorepo package scaffold

## Summary
Create the `packages/nestjs-mcp/` package with two sub-entrypoints: the core entrypoint (`@unique-ag/nestjs-mcp`) and the auth sub-entrypoint (`@unique-ag/nestjs-mcp/auth`). This establishes the build tooling, TypeScript config, exports map, and dependency boundaries so that importing core never pulls auth-only dependencies like `bcrypt`.

## Background / Context
The design merges the old `mcp-server-module` and `mcp-oauth` packages into one package with sub-entrypoints (same pattern as `@nestjs/core` + `@nestjs/testing`). This avoids EventEmitter bridges and cross-package interface alignment pain while keeping auth deps tree-shakeable. The existing `mcp-server-module` at `packages/mcp-server-module/` remains untouched during initial development; consumers migrate manually after the new package is stable.

Build tooling should use `tsup` for bundling (dual CJS/ESM with `.d.ts` generation) or plain `tsc` with project references — align with whichever the monorepo already uses. The monorepo uses `tsc` for `mcp-server-module` today, but `tsup` is preferred for sub-entrypoint support.

## Acceptance Criteria
- [ ] `packages/nestjs-mcp/` directory exists with `package.json`, `tsconfig.json`, and build config
- [ ] `package.json` name is `@unique-ag/nestjs-mcp`
- [ ] `package.json` `exports` map defines `"."` pointing to `src/index.ts` (core) and `"./auth"` pointing to `src/auth/index.ts`
- [ ] Peer dependencies: `@nestjs/common` (^10 || ^11), `@nestjs/core` (^10 || ^11), `zod` (^4), `@modelcontextprotocol/sdk` (^1.25)
- [ ] Core dependencies: `path-to-regexp`, `@nestjs/event-emitter`, `@nestjs/schedule`
- [ ] Auth sub-entrypoint optional dependencies (only pulled when `@unique-ag/nestjs-mcp/auth` is imported): `bcrypt`, `@nestjs/throttler`, `nestjs-zod`, `typeid-js`
- [ ] `src/index.ts` exists and exports a placeholder (e.g., `McpModule` class stub)
- [ ] `src/auth/index.ts` exists and exports a placeholder (e.g., `McpAuthModule` class stub)
- [ ] Build produces separate chunk/entrypoint for `auth` so that importing core does not bundle auth deps
- [ ] TypeScript strict mode enabled
- [ ] Biome config extends the monorepo root config

## BDD Scenarios

```gherkin
Feature: Monorepo package scaffold with isolated entrypoints

  Background:
    Given the "@unique-ag/nestjs-mcp" package is installed in a consumer project

  Rule: Core and auth entrypoints are independently importable

    Scenario: Core entrypoint resolves without pulling auth dependencies
      When the consumer imports "McpModule" from "@unique-ag/nestjs-mcp"
      Then the import resolves successfully at compile time and runtime
      And "bcrypt" is not in the resolved dependency graph
      And "@nestjs/throttler" is not in the resolved dependency graph

    Scenario: Auth entrypoint resolves and includes auth dependencies
      When the consumer imports "McpAuthModule" from "@unique-ag/nestjs-mcp/auth"
      Then the import resolves successfully at compile time and runtime
      And "bcrypt" is in the resolved dependency graph
      And "@nestjs/throttler" is in the resolved dependency graph

  Rule: The package builds correctly

    Scenario: Build produces output for both entrypoints
      Given the packages/nestjs-mcp source files
      When the build command is executed
      Then the build succeeds
      And output is produced for the core entrypoint
      And output is produced for the auth entrypoint
      And type declaration files are generated for both entrypoints

  Rule: Code quality standards are enforced

    Scenario: TypeScript strict mode catches type errors
      Given a source file in packages/nestjs-mcp with a type-unsafe assignment
      When the TypeScript compiler runs
      Then the compilation fails with a strict mode violation

    Scenario: Biome linting passes on all source files
      Given the packages/nestjs-mcp source files
      When the linter runs
      Then no lint violations are reported
```

## Dependencies
- Depends on: none (first ticket)
- Blocks: CORE-001, CORE-002, CORE-003, CORE-004, CORE-008 (direct dependents); all other CORE tickets transitively

## Interface Contract
This ticket produces the package structure consumed by all subsequent tickets:
- `packages/nestjs-mcp/` directory with build tooling
- `src/index.ts` — core entrypoint barrel export
- `src/auth/index.ts` — auth sub-entrypoint barrel export
- `package.json` with `exports` map for `"."` and `"./auth"`
- Subdirectory structure: `decorators/`, `interfaces/`, `services/`, `pipeline/`, `session/`, `context/`, `serialization/`, `helpers/`

## Technical Notes
- Reference existing `packages/mcp-server-module/package.json` for monorepo conventions (private, scripts, biome config)
- The `exports` map in `package.json` should look like:
  ```json
  {
    "exports": {
      ".": { "import": "./dist/index.js", "types": "./dist/index.d.ts" },
      "./auth": { "import": "./dist/auth/index.js", "types": "./dist/auth/index.d.ts" }
    }
  }
  ```
- If using `tsup`, configure two entry points: `src/index.ts` and `src/auth/index.ts`
- Auth deps should be listed under `optionalDependencies` or `peerDependencies` with `optional: true` in `peerDependenciesMeta` to avoid forcing install for core-only consumers
- Ensure `@nestjs/event-emitter` and `@nestjs/schedule` are in core deps (needed for session cleanup cron and future event-driven features)
- Directory structure:
  ```
  packages/nestjs-mcp/
    src/
      index.ts              # core entrypoint
      auth/
        index.ts            # auth sub-entrypoint
      decorators/
      interfaces/
      services/
      pipeline/
      session/
      context/
    tsconfig.json
    tsup.config.ts          # or tsconfig.build.json
    package.json
  ```
