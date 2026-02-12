# Design: Extract shared utilities into @unique-ag/utils

## Problem

Multiple services in the monorepo duplicate the same general-purpose utility code: `Redacted`, `Smeared`, `normalizeError`, timing helpers, and Zod codecs. As new services are added, each one copies these utilities again. There is no shared package for common, framework-agnostic utilities.

## Solution

### Overview

Create a new `packages/utils/` package (`@unique-ag/utils`) containing the five utility modules extracted from `sharepoint-connector` and `teams-mcp`, plus the general-purpose `smear()` function and `LogsDiagnosticDataPolicy` constant that `smeared.ts` depends on.

The package follows the existing monorepo conventions: flat `src/` directory, single barrel export via `index.ts`, TypeScript compiled to CommonJS in `dist/`, and `vitest` for testing. All utilities are pure functions and classes with no NestJS or framework dependencies.

Existing services are **not** updated to consume the new package as part of this work - they will adopt it later.

### Architecture

#### File structure

```
packages/utils/
├── package.json
├── tsconfig.json
├── vitest.config.ts
└── src/
    ├── index.ts              # barrel re-exports
    ├── redacted.ts           # Redacted<T> class
    ├── smear.ts              # smear() function + LogsDiagnosticDataPolicy constant
    ├── smeared.ts            # Smeared class, createSmeared, isSmearingActive, smearPath
    ├── normalize-error.ts    # normalizeError, sanitizeError
    ├── timing.ts             # elapsedMilliseconds, elapsedSeconds, elapsedSecondsLog
    ├── zod.ts                # json, typeid, stringToURL, isoDatetimeToDate, redacted
    └── __tests__/
        ├── redacted.spec.ts
        ├── smear.spec.ts           # extracted from logging.util.spec.ts
        ├── smeared.spec.ts
        ├── normalize-error.spec.ts
        ├── timing.spec.ts          # new
        └── zod.spec.ts             # new
```

#### Internal dependencies within the package

- `smeared.ts` → imports `smear()` from `./smear` and `LogsDiagnosticDataPolicy` from `./smear`
- `zod.ts` → imports `Redacted` from `./redacted`

#### External dependencies

```json
{
  "dependencies": {
    "serialize-error-cjs": "<current version>"
  },
  "peerDependencies": {
    "zod": "^4.1.5",
    "typeid-js": "^1.2.0"
  },
  "peerDependenciesMeta": {
    "zod": { "optional": true },
    "typeid-js": { "optional": true }
  },
  "devDependencies": {
    "typescript": "^5.9.2",
    "@types/node": "<current version>"
  }
}
```

- `serialize-error-cjs` is a hard dependency (used by `sanitizeError`)
- `zod` and `typeid-js` are optional peer dependencies - only needed by consumers that use the Zod codecs
- No NestJS peer dependencies needed; all utilities are framework-agnostic

#### Consumer API

All exports come through a single barrel:

```typescript
import { Redacted, normalizeError, sanitizeError } from '@unique-ag/utils';
import { Smeared, createSmeared, smearPath, smear } from '@unique-ag/utils';
import { elapsedMilliseconds, elapsedSeconds } from '@unique-ag/utils';
import { json, typeid, stringToURL, isoDatetimeToDate, redacted } from '@unique-ag/utils';
```

#### What changes in source files compared to originals

1. **`smear.ts`** (new file) - contains `smear()` extracted from `sharepoint-connector/src/utils/logging.util.ts` and `LogsDiagnosticDataPolicy` extracted from `sharepoint-connector/src/config/app.config.ts`. SharePoint-specific functions (`smearSiteNameFromPath`, `smearSiteIdFromPath`, `shouldConcealLogs`) stay in sharepoint-connector.

2. **`smeared.ts`** - imports change from `../config/app.config` → `./smear` and `./logging.util` → `./smear`.

3. **`zod.ts`** - import of `Redacted` stays as `./redacted` (same relative path within the new package).

4. **`redacted.ts`**, **`normalize-error.ts`**, **`timing.ts`** - copied as-is, no changes needed.

### Error Handling

Not applicable - these are pure utility functions. Each utility handles errors internally (e.g., `normalizeError` gracefully handles circular references, `smear` handles null/undefined).

### Testing Strategy

- Tests live in `src/__tests__/` directory, separate from source files
- Migrate existing test files from sharepoint-connector (`redacted.spec.ts`, `smeared.spec.ts`, `normalize-error.spec.ts`)
- Extract `smear()` tests from `logging.util.spec.ts` into `smear.spec.ts`
- Write new tests for `timing.ts` (currently untested) and `zod.ts` (no existing tests in teams-mcp)
- Tests import source modules from `../` (e.g., `import { Redacted } from '../redacted'`)
- Tests import `LogsDiagnosticDataPolicy` from `../smear` instead of `../config/app.config`
- Vitest config extends the root `globalConfig` (same pattern as `packages/mcp-oauth`)
- No setup files needed since all utilities are pure

## Out of Scope

- Updating existing services to consume `@unique-ag/utils` (adoption happens later)
- Extracting SharePoint-specific utilities (`smearSiteNameFromPath`, `smearSiteIdFromPath`, `shouldConcealLogs`)
- Extracting NestJS-coupled utilities (interceptors, filters, guards)
- Subpath exports - single barrel is sufficient for this package size
- Removing duplicate utility files from existing services (done when they adopt the package)

## Tasks

1. **Scaffold the package** - Create `packages/utils/` with `package.json`, `tsconfig.json`, and `vitest.config.ts` following existing monorepo conventions.

2. **Add `redacted.ts`** - Copy `Redacted<T>` class from sharepoint-connector. Migrate existing test file.

3. **Add `smear.ts`** - Extract the `smear()` function from `logging.util.ts` and `LogsDiagnosticDataPolicy` constant from `app.config.ts` into a single file. Extract relevant tests from `logging.util.spec.ts`.

4. **Add `smeared.ts`** - Copy `Smeared` class, `createSmeared`, `isSmearingActive`, and `smearPath` from sharepoint-connector. Update imports to reference local `./smear`. Migrate and update existing test file.

5. **Add `normalize-error.ts`** - Copy `normalizeError` and `sanitizeError` from sharepoint-connector (the superset version). Migrate existing test file.

6. **Add `timing.ts`** - Copy `elapsedMilliseconds`, `elapsedSeconds`, and `elapsedSecondsLog` from sharepoint-connector. Write new tests.

7. **Add `zod.ts`** - Copy Zod codecs (`json`, `typeid`, `stringToURL`, `isoDatetimeToDate`, `redacted`) from teams-mcp. Write new tests.

8. **Create barrel export** - Create `src/index.ts` re-exporting all public APIs from all modules.

9. **Verify** - Run `pnpm install`, `pnpm build`, `pnpm test`, and `pnpm check-types` to ensure the package compiles and all tests pass.
