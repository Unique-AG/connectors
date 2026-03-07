# CORE-019: Injectable parameters (DI-decorated params excluded from MCP schema)

## Summary
Implement detection and exclusion of NestJS dependency-injected parameters from MCP tool input schemas. Parameters decorated with `@Inject()`, `@InjectRepository()`, or other DI tokens are server-side injected and must not appear in the MCP `inputSchema` exposed to clients. Only non-decorated parameters (MCP input) and `@Ctx()` parameters are considered part of the MCP interface.

## Background / Context
FastMCP v2.14+ has `Depends(callable)` — parameters annotated with this are server-side injected and completely excluded from the MCP input schema (MCP clients never see them). In NestJS, the equivalent is any parameter decorated with `@Inject(token)`, `@InjectRepository()`, or custom DI tokens.

Currently, the `McpRegistryService` receives the class instance via NestJS DI, but all non-`@Ctx()` parameters on `@Tool()` methods are assumed to be MCP input parameters. This ticket adds scanning for DI-decorated parameters to exclude them from Zod schema generation and from the tool's `inputSchema`.

## Acceptance Criteria
- [ ] Parameters decorated with `@Inject(token)` are excluded from the tool's `inputSchema`
- [ ] Parameters decorated with `@InjectRepository()` are excluded from the tool's `inputSchema`
- [ ] Parameters decorated with other NestJS DI decorators (e.g., `@Optional()`, custom param decorators using `createParamDecorator`) are detected via metadata inspection
- [ ] Excluded parameters are still DI-injected at tool call time (handler receives all arguments)
- [ ] Only non-decorated parameters and `@Ctx()` parameter are considered MCP input
- [ ] `@Ctx()` parameter is excluded from `inputSchema` (already handled) but is NOT treated as DI-injected
- [ ] Metadata key `mcp:excluded_params` stores an array of excluded parameter indexes on method metadata
- [ ] The `listTools` response shows the correct `inputSchema` without injected parameter fields
- [ ] Works with both `z.ZodObject` and `Record<string, z.ZodType>` shorthand parameter definitions
- [ ] A `@McpExclude()` escape-hatch decorator is provided for marking arbitrary parameters as server-side-only
- [ ] `@McpExclude()` marks a parameter as framework-managed (already injected by the pipeline, e.g., via `@Ctx()`). The parameter factory skips DI resolution for excluded parameters. This is needed because `@Ctx()` parameters are already handled by the `@Ctx()` decorator — without `@McpExclude()`, the factory would try to resolve `McpContext` from DI unnecessarily

## BDD Scenarios

```gherkin
Feature: Injectable parameters excluded from MCP schema
  DI-injected parameters on tool methods must be hidden from MCP clients
  while still being resolved and passed to the handler at call time.

  Background:
    Given an MCP server is running with the nestjs-mcp module

  Rule: DI-decorated parameters are excluded from the tool input schema

    Scenario: Injected service does not appear in the tool schema
      Given a tool "cached_search" has a server-injected cache service and a "query" input parameter
      When a client calls listTools
      Then the "cached_search" input schema contains only the "query" field
      And no cache-related fields appear in the schema

    Scenario: Repository injection is excluded from the tool schema
      Given a tool "find_user" has an injected user repository and an "email" input parameter
      When a client calls listTools
      Then the "find_user" input schema contains only the "email" field

  Rule: Excluded parameters are still resolved and injected at call time

    Scenario: Client sends only MCP inputs and injected services are resolved automatically
      Given a tool "cached_search" has a server-injected cache service and a "query" input parameter
      When a client calls "cached_search" with { "query": "annual report" }
      Then the tool handler receives the resolved cache service instance
      And the tool handler receives "annual report" as the query value
      And the tool executes successfully

  Rule: @Ctx() is not treated as a DI-injected parameter

    Scenario: Context parameter, injected service, and MCP input coexist correctly
      Given a tool "db_search" has an MCP context parameter, a server-injected database service, and a "query" input parameter
      When a client calls listTools
      Then the "db_search" input schema contains only the "query" field
      When a client calls "db_search" with { "query": "test" }
      Then the tool handler receives the MCP context object
      And the tool handler receives the resolved database service
      And the tool handler receives "test" as the query value

  Rule: @McpExclude() decorator marks arbitrary parameters as server-side only

    Scenario: Parameter marked with @McpExclude() is hidden from clients
      Given a tool "process_data" has a parameter marked as server-side-only and a "payload" input parameter
      When a client calls listTools
      Then the "process_data" input schema contains only the "payload" field

    Scenario: Tool with all parameters excluded has an empty input schema
      Given a tool "health_check" where every parameter is either injected or marked as server-side-only
      When a client calls listTools
      Then the "health_check" input schema has no required fields and no properties
      When a client calls "health_check" with {}
      Then the tool executes successfully with all parameters resolved server-side
```

## Dependencies
- Depends on: CORE-001 (tool decorator — parameter metadata must be accessible)
- Depends on: CORE-005 (registry — must read excluded params during schema generation)
- Blocks: none

## Interface Contract

New decorator and metadata:
```typescript
// Metadata key for excluded parameter indexes
export const MCP_EXCLUDED_PARAMS = Symbol('MCP_EXCLUDED_PARAMS');

// Escape-hatch decorator for arbitrary exclusion
export function McpExclude(): ParameterDecorator;

// Stored metadata shape
interface ExcludedParamEntry {
  index: number;
  reason: 'inject' | 'inject-repository' | 'mcp-exclude' | 'custom-di';
}
```

## Technical Notes
- **Detection strategy**: Scan `Reflect.getMetadata('self:paramtypes', target, methodName)` and NestJS-standard param decorator metadata keys to detect DI-decorated params:
  - `@Inject(token)` stores metadata under `'self:properties_metadata'` or the NestJS `SELF_DECLARED_DEPS_METADATA` key
  - `@InjectRepository()` from `@nestjs/typeorm` uses `@Inject()` internally with a generated token
  - Custom param decorators created with `createParamDecorator()` store under NestJS route param metadata keys
- **Excluded indexes storage**: Store `mcp:excluded_params` array alongside tool registration using `Reflect.defineMetadata(MCP_EXCLUDED_PARAMS, entries, descriptor.value)`
- **Handler invocation**: When the tool is called, the pipeline runner must reconstruct the full argument array:
  1. Start with empty args array matching method parameter count
  2. Fill DI-injected params by resolving tokens from the NestJS container
  3. Fill `@Ctx()` param with the MCP context object
  4. Fill remaining positions with validated MCP input values
- **Schema generation**: When converting the Zod schema to JSON Schema for `inputSchema`, filter out keys corresponding to excluded parameter indexes. If using positional mapping (param index to schema key), maintain a mapping from parameter name to index
- **Edge case**: If all non-`@Ctx()` params are DI-injected, the tool's `inputSchema` should be `{ type: 'object', properties: {} }` (empty object, no required fields)
- **NestJS metadata detection**: Use `Reflect.getMetadata(PARAMTYPES_METADATA, target, propertyKey)` (where `PARAMTYPES_METADATA = 'design:paramtypes'`) to get the parameter type array. Filter out parameters that have `@Ctx()` metadata or `@McpExclude()` metadata. Remaining parameters are resolved via `moduleRef.resolve()` or `moduleRef.get()` based on their type token
- **Positional mapping example**:
  ```typescript
  @Tool({ name: 'search', description: 'Search' })
  async search(
    query: string,          // position 0: no DI metadata → resolved from MCP args by matching the TypeScript parameter name "query"
    @Ctx() ctx: McpContext, // position 1: @Ctx() metadata → injects McpContext (excluded from inputSchema)
    @Inject(MY_SERVICE) svc: MyService, // position 2: @Inject() metadata → resolves MY_SERVICE from DI (excluded from inputSchema)
  ): Promise<string> { ... }
  ```
- File location: `packages/nestjs-mcp/src/decorators/mcp-exclude.decorator.ts` for the `@McpExclude()` decorator; detection logic in `packages/nestjs-mcp/src/registry/param-scanner.ts`
