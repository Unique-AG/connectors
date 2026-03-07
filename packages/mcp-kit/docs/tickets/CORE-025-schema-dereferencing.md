# CORE-025: Schema dereferencing for MCP tool schemas

## Summary
Implement automatic `$ref` dereferencing for JSON schemas generated from Zod types, producing self-contained `inputSchema` in `listTools` responses. Controlled via `derefSchemas` option in `McpModuleOptions` (default: `true`).

## Background / Context
FastMCP auto-dereferences `$ref` entries in JSON schemas at serve-time (when generating `listTools` inputSchema). This produces self-contained schemas that MCP clients can use without resolving references. Opt-out via `dereference_schemas=False`.

In NestJS, Zod v4's `toJSONSchema()` may produce `$ref`-based schemas for complex, nested, or recursive types. When `$ref` entries reference `$defs` within the same schema, clients must resolve these references before they can validate input. Many MCP clients (especially LLMs) cannot resolve `$ref` references and need fully inlined schemas. This ticket adds a dereferencing pass that inlines all `$ref` references to produce self-contained schemas.

## Acceptance Criteria
- [ ] `derefSchemas` option added to `McpOptions`: `boolean`, default `true`
- [ ] When `derefSchemas: true`, all `$ref` entries in tool `inputSchema` are resolved and inlined before returning in `listTools` responses
- [ ] When `derefSchemas: false`, `$ref` entries are preserved as-is in `listTools` responses
- [ ] Dereferencing handles `$defs`-based references (the format `toJSONSchema()` produces): `{ "$ref": "#/$defs/MyType" }` is replaced with the inlined definition
- [ ] After dereferencing, the `$defs` block is removed from the schema (no orphaned definitions)
- [ ] Circular/recursive schemas are handled gracefully: detect cycles and replace the recursive `$ref` with `{}` (empty schema, accepts anything) to prevent infinite inlining
- [ ] Dereferencing preserves all other schema properties (`description`, `title`, `default`, `examples`, etc.)
- [ ] `derefSchemas` also applies to `outputSchema` if present on tools
- [ ] Simple flat schemas (no `$ref`) are unaffected by the dereferencing pass (same output)
- [ ] `derefSchema(schema: JsonSchema): JsonSchema` utility function exported from `@unique-ag/nestjs-mcp` for consumer use
- [ ] No external dependencies required — inline implementation preferred over adding `json-schema-ref-parser`

## BDD Scenarios

```gherkin
Feature: Schema dereferencing for MCP tool schemas
  Tool input schemas are automatically dereferenced so that MCP clients
  (especially LLMs) receive self-contained schemas without $ref pointers.

  Background:
    Given an MCP server is running with schema dereferencing enabled by default

  Rule: Nested type references are inlined into self-contained schemas

    Scenario: A tool with a nested Address type has a fully inlined schema
      Given a tool "create_order" has an "address" parameter using a reusable Address type
      And the Address type has fields "street" (string) and "city" (string)
      When a client calls listTools
      Then the "create_order" input schema contains "address" as an inline object with "street" and "city"
      And the schema contains no "$ref" pointers
      And the schema contains no "$defs" block

    Scenario: Two parameters referencing the same type are both inlined
      Given a tool "ship_order" has "billing" and "shipping" parameters both using the Address type
      When a client calls listTools
      Then both "billing" and "shipping" contain the full inline Address schema
      And the schema contains no "$defs" block

    Scenario: Schema metadata is preserved after dereferencing
      Given a tool "find_user" has a parameter using a type with a description, default value, and examples
      When a client calls listTools
      Then the inlined schema retains the description, default value, and examples

  Rule: Dereferencing can be disabled

    Scenario: Schemas retain $ref pointers when dereferencing is disabled
      Given an MCP server is configured with schema dereferencing disabled
      And a tool "create_order" has an "address" parameter using a reusable Address type
      When a client calls listTools
      Then the "create_order" input schema contains a "$ref" pointer for the address field
      And the schema contains a "$defs" block with the Address definition

  Rule: Recursive schemas are handled gracefully

    Scenario: A recursive tree-node schema does not cause infinite expansion
      Given a tool "process_tree" has a parameter using a TreeNode type
      And TreeNode has a "value" (string) and "children" (array of TreeNode) field
      When a client calls listTools
      Then the "process_tree" input schema inlines the top-level TreeNode structure
      And the recursive self-reference is replaced with an open schema
      And the server does not hang or crash

  Rule: Simple schemas pass through unchanged

    Scenario: A flat schema without references is returned as-is
      Given a tool "search" has parameters "query" (string) and "limit" (number) with no nested types
      When a client calls listTools
      Then the "search" input schema is a plain object with "query" and "limit" fields
      And no transformation artifacts are introduced

  Rule: Output schemas are also dereferenced

    Scenario: Both input and output schemas are dereferenced
      Given a tool "transform_data" has both an input schema and an output schema containing nested type references
      When a client calls listTools
      Then both the input schema and the output schema are fully inlined
      And neither schema contains "$ref" pointers
```

## FastMCP Parity
- **FastMCP**: Auto-dereferences at serve-time via `jsonref.replace_refs()`. Opt-out with `dereference_schemas=False` on server constructor.
- **NestJS**: `derefSchemas: boolean` (default `true`) on `McpOptions`. Uses an inline implementation (no external library).
- **Difference**: Same behavior. FastMCP uses `jsonref` Python library; we implement a lightweight inline dereferencer to avoid adding a dependency.

## Dependencies
- **Depends on:** CORE-012 — McpModule configuration (new `derefSchemas` option)
- **Depends on:** CORE-013 — MCP handlers (dereferencing applied in `listTools` response construction)
- **Blocks:** nothing

## Technical Notes
- Inline dereferencing implementation:
  ```typescript
  export function derefSchema(schema: Record<string, unknown>): Record<string, unknown> {
    const defs = (schema.$defs ?? schema.definitions ?? {}) as Record<string, unknown>;
    const visiting = new Set<string>(); // cycle detection

    function resolve(node: unknown): unknown {
      if (node === null || typeof node !== 'object') return node;
      if (Array.isArray(node)) return node.map(resolve);

      const obj = node as Record<string, unknown>;
      if (typeof obj.$ref === 'string') {
        const refPath = obj.$ref as string;
        const match = refPath.match(/^#\/\$defs\/(.+)$/);
        if (match && defs[match[1]]) {
          if (visiting.has(match[1])) return {}; // circular ref → empty schema
          visiting.add(match[1]);
          const resolved = resolve(defs[match[1]]);
          visiting.delete(match[1]);
          return resolved;
        }
        return obj; // external $ref — leave as-is
      }

      const result: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(obj)) {
        if (key === '$defs' || key === 'definitions') continue; // strip defs block
        result[key] = resolve(value);
      }
      return result;
    }

    return resolve(schema) as Record<string, unknown>;
  }
  ```
- Integration point: In `McpToolsHandler.listTools()` (CORE-013), after generating the JSON schema via `toJSONSchema()`, conditionally apply `derefSchema()`:
  ```typescript
  let inputSchema = toJSONSchema(tool.schemas.input);
  if (this.options.derefSchemas !== false) {
    inputSchema = derefSchema(inputSchema);
  }
  ```
- Edge case: `toJSONSchema()` in Zod v4 uses `$defs` (not `definitions`). The implementation handles both for forward compatibility.
- Edge case: External `$ref` (e.g., `$ref: "https://..."`) are left as-is — only local `#/$defs/` references are inlined.
- Performance: Dereferencing runs once per `listTools` call, not per tool call. For servers with many tools, consider caching the dereferenced schemas (they don't change unless tools are dynamically re-registered).
- `McpOptions` update: Add `derefSchemas?: boolean` (default `true`) to the interface in CORE-012.
- File locations:
  - `packages/nestjs-mcp/src/utils/deref-schema.ts` — dereferencing utility
  - Integration in `packages/nestjs-mcp/src/services/handlers/mcp-tools.handler.ts`
