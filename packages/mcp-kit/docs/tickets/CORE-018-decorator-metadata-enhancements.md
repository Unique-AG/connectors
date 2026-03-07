# CORE-018: Decorator metadata enhancements (meta, icons, version)

## Summary
Add `meta`, `icons`, and `version` fields to all three decorator option interfaces (`@Tool()`, `@Resource()`, `@Prompt()`), and add `title` to `@Prompt()`. These fields provide FastMCP v2.11+/v2.13+/v3.0+ parity: `meta` passes custom key-value metadata to clients via `_meta`, `icons` provides visual representations for client UIs, and `version` enables multiple implementations under the same name with clients receiving the highest version.

## Background / Context
FastMCP has progressively added metadata fields to tool/resource/prompt definitions:
- **v2.11+**: `meta` — arbitrary key-value metadata forwarded to clients in the `_meta` field of list responses
- **v2.13+**: `icons` — array of `Icon` objects (`{ uri, mimeType? }`) for visual display in MCP clients
- **v3.0+**: `version` — string or integer version identifier; when multiple implementations register the same name, clients receive the one with the highest version
- **Prompts also have `title`** — a human-readable display name separate from the identifier `name`

These are cross-cutting enhancements that apply uniformly to CORE-001, CORE-002, and CORE-003.

## Acceptance Criteria

### meta (all three decorators)
- [ ] `@Tool({ meta: { ... } })` stores metadata and emits it as `_meta` in `listTools` responses
- [ ] `@Resource({ meta: { ... } })` stores metadata and emits it as `_meta` in `listResources` responses
- [ ] `@Prompt({ meta: { ... } })` stores metadata and emits it as `_meta` in `listPrompts` responses
- [ ] `meta` is optional on all three decorators (defaults to `undefined`)
- [ ] `meta` values are serializable JSON (no functions, no circular refs)

### icons (all three decorators)
- [ ] `@Tool({ icons: [...] })` stores icons and includes them in `listTools` responses
- [ ] `@Resource({ icons: [...] })` stores icons and includes them in `listResources` responses
- [ ] `@Prompt({ icons: [...] })` stores icons and includes them in `listPrompts` responses
- [ ] `icons` is optional on all three decorators (defaults to `undefined`)
- [ ] Each icon conforms to `McpIcon` interface: `{ uri: string; mimeType?: string }`

### version (all three decorators)
- [ ] `@Tool({ version: '2.0' })` stores version in metadata
- [ ] `@Resource({ version: 1 })` stores version in metadata
- [ ] `@Prompt({ version: '1.0.0' })` stores version in metadata
- [ ] `version` is optional on all three decorators (defaults to `undefined`)
- [ ] When two implementations register the same name with different versions, the registry keeps the one with the highest version (numeric comparison for numbers, semver-style for strings)
- [ ] Version comparison respects `onDuplicate` setting from CORE-012 — `version` only applies when duplicates are allowed

### title on @Prompt
- [ ] `@Prompt({ title: 'Compose Email' })` stores title as a display-only label
- [ ] `title` appears in `listPrompts` response as the `title` field
- [ ] `title` is separate from `name` (which is the identifier used in `prompts/get`)
- [ ] `title` is optional (defaults to `undefined`)

## BDD Scenarios

```gherkin
Feature: Decorator Metadata Enhancements
  Tools, resources, and prompts support optional meta, icons, and version
  fields that are forwarded to clients in list responses. Prompts also
  support a display title separate from the identifier name.

  Rule: Custom metadata is forwarded in list responses

    Scenario: Tool with custom metadata includes it in the tool list
      Given a tool "search_emails" with custom metadata category "email" and priority "high"
      When a client requests the tool list
      Then the "search_emails" entry includes metadata with category "email" and priority "high"

    Scenario: Tool without custom metadata omits the metadata field
      Given a tool "simple_tool" with no custom metadata
      When a client requests the tool list
      Then the "simple_tool" entry does not include a metadata field

  Rule: Icons are included in list responses

    Scenario: Resource with an icon includes it in the resource list
      Given a resource "config://app" with an SVG icon at "https://example.com/config.svg"
      When a client requests the resource list
      Then the resource entry includes the icon URI and media type "image/svg+xml"

    Scenario: Prompt with an icon includes it in the prompt list
      Given a prompt "draft-email" with a PNG icon at "https://example.com/email.png"
      When a client requests the prompt list
      Then the prompt entry includes the icon URI and media type "image/png"

  Rule: Version controls which implementation is exposed for duplicate names

    Scenario: Higher-versioned tool wins when duplicates are allowed
      Given a tool "search" registered at version 1
      And another tool "search" registered at version 2
      And duplicate names are configured to be replaced
      When a client requests the tool list
      Then only the version 2 implementation of "search" is listed

  Rule: Prompt title is a display label separate from the identifier

    Scenario: Prompt with a title shows the title in the prompt list
      Given a prompt with name "draft-outreach" and title "Compose Outreach Email"
      When a client requests the prompt list
      Then the prompt entry includes title "Compose Outreach Email"
      And the prompt is identified by name "draft-outreach"
```

## Dependencies
- Depends on: CORE-001, CORE-002, CORE-003 (extends their decorator option interfaces)
- Depends on: CORE-005 (registry must handle version comparison and _meta emission)
- Depends on: CORE-012 (McpIcon type defined there; onDuplicate interacts with version)
- Blocks: none

## Interface Contract

Shared icon type (exported from `@unique-ag/nestjs-mcp`):
```typescript
export interface McpIcon {
  uri: string;
  mimeType?: string;
}
```

Extended fields added to `ToolOptions`, `ResourceOptions`, `PromptOptions`:
```typescript
// Added to all three option interfaces:
icons?: McpIcon[];
meta?: Record<string, unknown>;
version?: string | number;

// Added to PromptOptions only:
title?: string;
```

Extended fields added to `ToolMetadata`, `ResourceMetadata`, `PromptMetadata`:
```typescript
// Added to all three metadata interfaces:
icons?: McpIcon[];
meta?: Record<string, unknown>;
version?: string | number;

// Added to PromptMetadata only:
title?: string;
```

## Technical Notes
- `McpIcon` interface uses `uri` + `mimeType` (matching MCP protocol's Icon type). The `McpIcon` name avoids collision with DOM's `Icon` type. Already referenced in CORE-012's `serverInfo.icons` (which uses `url` + `mediaType` for the server-level icon — note the naming difference; CORE-012 follows the MCP `initialize` response schema while decorator icons follow the MCP list response schema)
- `meta` is stored as-is in decorator metadata and emitted as `_meta` in list responses. The underscore prefix is an MCP protocol convention for extension metadata
- Version comparison logic:
  - If both versions are numbers, compare numerically
  - If both are strings, use semver comparison (major.minor.patch) — consider using a lightweight semver compare utility
  - Mixed types (string vs number) — convert both to string and compare lexicographically
  - Version comparison only triggers when two registrations share the same name and `onDuplicate` is not `'error'`
- `title` on prompts maps directly to the MCP protocol's `title` field in `ListPromptsResult` items (added in protocol version 2025-03-26)
- File locations: changes span across `tool.decorator.ts`, `resource.decorator.ts`, `prompt.decorator.ts`, and their corresponding metadata interfaces
