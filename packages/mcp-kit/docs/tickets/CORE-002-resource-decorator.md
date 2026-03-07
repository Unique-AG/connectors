# CORE-002: @Resource() decorator (unified)

## Summary
Implement a unified `@Resource()` decorator that replaces both the old `@Resource()` and `@ResourceTemplate()` decorators. The framework auto-detects `{param}` patterns in the URI to determine whether to register as a static resource or a resource template, eliminating the need for two separate decorators.

## Background / Context
A single `@Resource()` decorator handles both static resources and resource templates. If the URI contains `{...}` placeholders, it's a template; otherwise, it's static. This reduces API surface and prevents the common mistake of using the wrong decorator.

The MCP protocol distinguishes between static resources (listed in `resources/list`) and resource templates (listed in `resources/templates/list`). The decorator produces metadata with a `kind` discriminator so the registry and handlers can register them correctly with the SDK.

## Acceptance Criteria
- [ ] `@Resource()` is exported from `@unique-ag/nestjs-mcp`
- [ ] `@ResourceTemplate()` is NOT exported (deleted from API surface)
- [ ] Static URI (no `{...}`) registers as a static resource
- [ ] URI with `{param}` patterns registers as a resource template
- [ ] `name` defaults to the method name (camelCase preserved, as MCP resource names are freeform). This applies to both static resources and resource templates
- [ ] `description` is optional
- [ ] `mimeType` is optional
- [ ] Metadata includes a `kind` discriminator: `'static' | 'template'`
- [ ] For templates, extracted parameter names are stored in metadata (e.g., `['user_id']` from `users://{user_id}/profile`)
- [ ] URI templates support RFC 6570 Level 4 wildcard params `{param*}` — captures multiple path segments including slashes (e.g., `files://{path*}` matches `files://a/b/c`)
- [ ] URI templates support RFC 6570 Level 4 query params `{?param,param2}` — optional query string params with defaults (e.g., `data://{id}{?format,limit}`)
- [ ] Wildcard params stored in `templateParams` with a `*` suffix (e.g., `['path*']`)
- [ ] Query params stored separately in `queryParams` array (e.g., `['format', 'limit']`)
- [ ] Query params are optional by convention (handlers receive `undefined` for omitted query params)
- [ ] Mixed templates with path params, wildcard params, and query params are supported (e.g., `repo://{owner}/{repo}/files/{path*}{?ref,format}`)
- [ ] `icons` option stores array of `McpIcon` objects and includes them in `listResources` / `listResourceTemplates` responses (v2.13.0+ parity)
- [ ] `meta` option stores custom metadata and emits it as `_meta` in list responses (v2.11.0+ parity)
- [ ] `version` option stores a string or number version identifier in metadata (v3.0.0+ parity)
- [ ] `annotations` option stores advisory hints (`readOnlyHint`, `idempotentHint`) in metadata
- [ ] Metadata stored under `MCP_RESOURCE_METADATA` symbol
- [ ] `ResourceOptions` and `ResourceMetadata` TypeScript interfaces exported

## BDD Scenarios

```gherkin
Feature: Unified @Resource() decorator for static and template resources

  Rule: URI pattern determines static vs template registration

    Scenario: Static URI registers as a static resource
      Given a resource with URI "config://app/settings"
      When an MCP client lists resources
      Then "config://app/settings" appears in the static resources list
      And it does not appear in the resource templates list

    Scenario: URI with placeholders registers as a resource template
      Given a resource with URI "users://{user_id}/profile"
      When an MCP client lists resource templates
      Then a template with URI pattern "users://{user_id}/profile" appears
      And it does not appear in the static resources list

    Scenario: URI with multiple placeholders registers as a template
      Given a resource with URI "orgs://{org_id}/teams/{team_id}"
      When an MCP client lists resource templates
      Then a template with both "org_id" and "team_id" parameters appears

    Scenario: File URI with no placeholders registers as static
      Given a resource with URI "file:///data/config.json"
      When an MCP client lists resources
      Then "file:///data/config.json" appears in the static resources list

  Rule: Resource name defaults to the method name

    Scenario: Name defaults to the method name
      Given a method named "getSettings" decorated as a resource with URI "config://app/settings"
      When an MCP client lists resources
      Then the resource name is "getSettings"

    Scenario: Explicit name overrides the method name
      Given a resource with URI "config://app/settings" and name "app-settings"
      When an MCP client lists resources
      Then the resource name is "app-settings"

  Rule: MIME type is communicated to clients

    Scenario: MIME type appears in resource listing
      Given a resource with URI "config://app/settings" and MIME type "application/json"
      When an MCP client lists resources
      Then the resource entry reports MIME type "application/json"

  Rule: Wildcard and query parameters are supported in templates

    Scenario: Wildcard parameter captures multiple path segments
      Given a resource template with URI "files://{path*}"
      When an MCP client reads "files://a/b/c.txt"
      Then the handler receives path "a/b/c.txt"

    Scenario: Query parameters are extracted from the URI template
      Given a resource template with URI "data://{id}{?format,limit}"
      When an MCP client reads "data://123?format=json&limit=10"
      Then the handler receives id "123", format "json", and limit "10"

    Scenario: Omitted query parameters default to undefined
      Given a resource template with URI "data://{id}{?format,limit}"
      When an MCP client reads "data://123" with no query parameters
      Then the handler receives id "123", format undefined, and limit undefined

    Scenario: Mixed template with path, wildcard, and query parameters
      Given a resource template with URI "repo://{owner}/{repo}/files/{path*}{?ref,format}"
      When an MCP client reads "repo://acme/widgets/files/src/main.ts?ref=v2"
      Then the handler receives owner "acme", repo "widgets", path "src/main.ts", ref "v2", and format undefined

  Rule: Icons, meta, and annotations appear in resource listings

    Scenario: Icons and meta are included in the resources list
      Given a resource with URI "config://app/settings"
      And the resource has an icon at "https://example.com/settings.svg"
      And the resource has meta with category "configuration"
      When an MCP client lists resources
      Then the resource entry includes the icon URI
      And the resource entry includes metadata with category "configuration"

    Scenario: Read-only annotation is communicated to clients
      Given a resource with URI "config://app/settings" and a read-only hint
      When an MCP client lists resources
      Then the resource entry indicates it is read-only
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Blocks: CORE-005, SDK-004, CORE-015

## Interface Contract
Consumed by CORE-005 (registry), CORE-013 (handlers), SDK-004 (resource subscriptions):
```typescript
export const MCP_RESOURCE_METADATA = Symbol('MCP_RESOURCE_METADATA');

export interface ResourceOptions {
  uri: string;
  name?: string;
  description?: string;
  mimeType?: string;
  icons?: McpIcon[];                       // visual representations for client display (v2.13.0+ parity)
  meta?: Record<string, unknown>;          // custom metadata passed to clients in _meta field (v2.11.0+ parity)
  version?: string | number;               // version identifier; highest version wins on duplicate name (v3.0.0+ parity)
  annotations?: {                          // advisory metadata about resource behavior
    readOnlyHint?: boolean;
    idempotentHint?: boolean;
  };
}

export interface ResourceMetadata {
  uri: string;
  name: string;                          // resolved (auto-derived or explicit)
  description?: string;
  mimeType?: string;
  kind: 'static' | 'template';          // auto-detected from URI
  templateParams: string[];              // path + wildcard param names (empty for static; wildcard has '*' suffix)
  queryParams: string[];                 // query param names from {?...} (empty if none)
  icons?: McpIcon[];                     // visual representations for client display
  meta?: Record<string, unknown>;        // custom metadata emitted as _meta
  version?: string | number;             // version identifier for multi-version support
  annotations?: {                        // advisory metadata about resource behavior
    readOnlyHint?: boolean;
    idempotentHint?: boolean;
  };
  methodName: string;
}
```

## Technical Notes
- **URI template parsing** must handle RFC 6570 Level 4 patterns:
  - Simple params: `/\{(\w+)\}/g` — e.g., `{user_id}`
  - Wildcard (explode) params: `/\{(\w+)\*\}/g` — e.g., `{path*}` — captures multi-segment paths including `/`
  - Query params: `/\{\?([^}]+)\}/g` — e.g., `{?format,limit}` — split on `,` for individual names
- Parsing order: extract query params first (remove `{?...}` from URI), then extract path/wildcard params from remainder
- If any params found, set `kind: 'template'`; if none, set `kind: 'static'`
- Consider using an RFC 6570 library (e.g., `uri-template-lite` or `url-template`) for expansion/matching at runtime. Dependency choice tracked in INFRA-001
- **FastMCP parity:** FastMCP supports wildcard `{path*}` and query `{?param}` via full RFC 6570. Our implementation must match this capability for resource URI flexibility
- Metadata storage: `Reflect.defineMetadata(MCP_RESOURCE_METADATA, resolvedMetadata, descriptor.value)`
- Use a single `MCP_RESOURCE_METADATA` symbol (replaces both `MCP_RESOURCE_METADATA_KEY` and `MCP_RESOURCE_TEMPLATE_METADATA_KEY` from the old code)
- **URI uniqueness**: Two resources cannot share the same `uri`. The `onDuplicate` setting from CORE-012 applies to resource URIs (not names) since URIs are the primary lookup key for resources
- File location: `packages/nestjs-mcp/src/decorators/resource.decorator.ts`
- The registry (CORE-005) will use the `kind` discriminator to register with the correct SDK method
