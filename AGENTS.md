# Project Instructions

## Environment
- Python services (any `services/*/pyproject.toml`) are driven by `uv`, not pnpm/turbo, and their
  commands live in `DEVELOP.md` under "Python Services". Read the git-worktree trap there before you
  believe a basedpyright run that reports thousands of errors: a worktree without a synced `.venv`
  resolves no import and invents every one of them.

## Code Comments
- Keep comments minimal - code should be self-explanatory
- Only add comments for complex algorithms, unexpected behavior, or non-obvious business logic
- Add JSDoc comments only for complex methods with multiple parameters or intricate logic
- Avoid obvious comments that just restate what the code does
- Prefer clear variable and function names over explanatory comments

## Code Style
- Write clean, readable code that minimizes the need for comments
- Use descriptive naming conventions
- Keep functions focused and single-purpose
- Avoid the use of `any`. Always use proper types or `unknown` with a type guard.
- When `any` is absolutely necessary (e.g., testing private methods, untyped third-party libraries), add a biome-ignore comment with explanation:
  ```typescript
  // biome-ignore lint/suspicious/noExplicitAny: Mock override private method
  vi.spyOn(service as any, 'validatePKCE').mockReturnValue(true);
  ```
- When writing code focuse on consistency and follow DRY principles
- Add export only when what you are exporting is actually used in another file
- Never mutate function arguments. Don't push into, reassign, or otherwise modify a value the caller passed in, and don't use out-parameters. Return new data instead.

## Import Ordering
- Follow this import order:
  1. Node.js built-in modules (e.g., `import { createHmac } from 'node:crypto'`)
  2. External packages (e.g., `import { UnauthorizedException } from '@nestjs/common'`)
  3. Testing utilities (e.g., `import { TestBed } from '@suites/unit'`)
  4. Internal modules and types
- Group related imports together
- Order imports alphabetically within each group when practical

## Generated Files
- Don't create README files for generated code

## Formatting

- `ruff` owns `.py`. `biome` owns everything else it can parse, in every service and package,
  whatever language the service is written in.
- `biome.json` excludes four categories and nothing else. A new service needs no new entry if it
  follows them:
  1. build and test output — `dist`, `coverage`
  2. tool caches and editor state — `.turbo`, `.pnpm-store`, `.venv`, `.zed`
  3. generated files — anything under `@generated`, anything named `*.generated.*`, `drizzle`,
     and a chart's `values.schema.json`
  4. paths owned by another toolchain — `.github` (yaml), `scripts` (Deno)
- Name a generated file `<name>.generated.<ext>` and biome ignores it without an edit to
  `biome.json`.
- `html.parser.interpolation` is on, so a Jinja or Handlebars template parses and is checked
  rather than skipped. Helm templates are yaml and `.tpl`, which biome does not parse at all.

## Tests

### Test Implementation Guidelines

#### Test Naming
- When writing tests, avoid the word 'should' in the 'it' function name. Use present tense instead, e.g. instead of `it('should register a client')`, write `it('registers a client')`

#### Guidelines
- Follow the guidelines in https://www.betterspecs.org/ but adapted to what is possible with vitest.

#### Using @suites/unit TestBed
- When mocking module options with TestBed, use `.impl()` pattern instead of `.using()`:
  ```typescript
  const { unit, unitRef } = await TestBed.solitary(ServiceClass)
    .mock<OptionsType>(OPTIONS_TOKEN)
    .impl((stubFn) => ({ ...stubFn(), ...options }))
    .compile();
  ```

#### Testing Private Methods
- When testing private methods is necessary, use type casting with explanatory comment:
  ```typescript
  // biome-ignore lint/suspicious/noExplicitAny: Override private method to test cleanup
  const cleanup = (service as any).cleanupExpiredTokens.bind(service);
  ```

#### Test Data Setup
- Create complete mock objects with all required properties
- Extract common test data to variables for reuse
- Use descriptive names for mock data (e.g., `mockClient`, `mockSession`, `mockAuthCode`)

#### Assertions
- Be specific with assertions - check exact values and method calls
- Verify both positive and negative cases
- Test error conditions and edge cases