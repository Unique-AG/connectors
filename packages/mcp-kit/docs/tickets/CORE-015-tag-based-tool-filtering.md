# CORE-015: Tag-based tool filtering

## Summary
Add a `tags: string[]` option to `@Tool()`, `@Resource()`, and `@Prompt()` decorators. Tags are included in `listTools` / `listResources` / `listPrompts` response metadata. An optional `enabledTags` allowlist and `disabledTags` denylist in `McpModule.forRoot()` control which tagged items are exposed to clients. A `tagScopes` mapping enables conditional scope requirements — if a component has a specific tag, specific auth scopes are automatically required via `TagScopeGuard`.

## Background / Context
FastMCP (Python) supports tagging tools and filtering by tags. This is useful for:
- Feature flagging (enable/disable tool groups without code changes)
- Multi-tenant scenarios (different tenants see different tool sets)
- Development vs production tool sets
- Categorization for client-side grouping
- Security scoping — automatically requiring auth scopes for tagged components

Tags are purely server-side metadata — the MCP protocol doesn't define a standard tag field, but they can be included in the `_meta` field of list responses and used for server-side filtering.

FastMCP supports three tag operations:
- `mcp.enable(tags={"public"}, only=True)` — allowlist mode (our `enabledTags`)
- `mcp.disable(tags={"internal", "deprecated"})` — denylist mode (our `disabledTags`)
- `restrict_tag("admin", require_scopes("admin:*"))` — conditional scope requirement (our `tagScopes` + `TagScopeGuard`)

These can be combined: allowlist + denylist together, and tag-based scope restrictions apply on top of both.

## Acceptance Criteria

### Allowlist (enabledTags)
- [ ] `@Tool({ tags: ['email', 'read'] })` adds tags to tool metadata
- [ ] `@Resource({ tags: ['config'] })` adds tags to resource metadata
- [ ] `@Prompt({ tags: ['onboarding'] })` adds tags to prompt metadata
- [ ] Tags are included in `listTools` / `listResources` / `listPrompts` response metadata (in `_meta.tags`)
- [ ] `McpModule.forRoot({ enabledTags: ['email', 'config'] })` filters: only items with at least one matching tag are exposed
- [ ] Items with NO tags are always exposed (untagged = always visible)
- [ ] If `enabledTags` is not set, all items are exposed regardless of tags
- [ ] `enabledTags` can be a function `(tags: string[]) => boolean` for dynamic filtering
- [ ] Tags are available in `McpOperationContext` for use in guards/interceptors

### Denylist (disabledTags)
- [ ] `McpModule.forRoot({ disabledTags: ['internal', 'deprecated'] })` hides components with ANY of these tags
- [ ] Denied components do not appear in list responses (listTools, listResources, listPrompts)
- [ ] Denied components return an error if called directly (not just hidden from lists)
- [ ] `disabledTags` can be combined with `enabledTags`: `{ enabledTags: ['public'], disabledTags: ['deprecated'] }` — show only public, but explicitly hide deprecated even if also tagged public
- [ ] When both are set, `disabledTags` takes precedence over `enabledTags` (deny wins)
- [ ] `disabledTags` can be a function `(tags: string[]) => boolean` for dynamic filtering

### Runtime dynamic tag changes
- [ ] `McpSessionService.disableTags(tags: string[])` dynamically adds tags to the session-level denylist
- [ ] `McpSessionService.enableTags(tags: string[])` dynamically adds tags to the session-level allowlist
- [ ] Dynamic tag changes trigger `listChanged` notifications (tools/resources/prompts) per SDK-005
- [ ] Session-level tag overrides are layered on top of global `forRoot` config (session deny + global deny = union)

### Conditional scope requirements (tagScopes + TagScopeGuard)
- [ ] `McpModule.forRoot({ tagScopes: { 'admin': ['admin:write'], 'sensitive': ['data:read', 'data:write'] } })` configures tag→scope mappings
- [ ] `TagScopeGuard` reads the tag→scope mapping from module config and the component's tags from registry metadata
- [ ] If a component has a tag present in `tagScopes`, the guard requires the associated scopes from the caller's identity
- [ ] Multiple tags on one component — the required scopes are the UNION of all matching tag→scope entries (most restrictive)
- [ ] Components without any tags in `tagScopes` are unaffected by the guard
- [ ] `TagScopeGuard` is registered via `APP_GUARD` (standard NestJS global guard registration)
- [ ] `TagScopeGuard` also applies at list time (per CORE-013 filtering) — users without required scopes don't see tagged components in list responses
- [ ] `TagScopeGuard` is exported from `@unique-ag/nestjs-mcp` for explicit registration

## BDD Scenarios

```gherkin
Feature: Tag-based Tool Filtering
  Tools, resources, and prompts can be tagged for allowlist/denylist filtering,
  runtime visibility changes, and automatic scope requirements via tag-scope mappings.

  Rule: Tag metadata is exposed in list responses

    Scenario: Tags appear in the tool list metadata
      Given a tool "search_emails" tagged with "email" and "read"
      When a client requests the tool list
      Then the "search_emails" entry includes tags "email" and "read" in its metadata

  Rule: Allowlist filtering (enabledTags)

    Scenario: Only tools matching the enabled tags are listed
      Given tools:
        | name          | tags            |
        | search_emails | email, read     |
        | send_email    | email, write    |
        | list_files    | files           |
      And the server is configured with enabled tags "email"
      When a client requests the tool list
      Then "search_emails" and "send_email" appear
      And "list_files" does not appear

    Scenario: Untagged tools are always visible when an allowlist is set
      Given a tool "search_emails" tagged with "email"
      And a tool "add_numbers" with no tags
      And the server is configured with enabled tags "email"
      When a client requests the tool list
      Then both "search_emails" and "add_numbers" appear

    Scenario: All tools are visible when no allowlist is configured
      Given tools with various tags
      And the server is configured without an enabled tags setting
      When a client requests the tool list
      Then all tools appear regardless of their tags

    Scenario: Dynamic tag filter function excludes deprecated tools
      Given the server is configured with a tag filter that excludes tools tagged "deprecated"
      And a tool "old_search" tagged with "email" and "deprecated"
      When a client requests the tool list
      Then "old_search" does not appear

  Rule: Denylist filtering (disabledTags)

    Scenario: Disabled-tagged tool is hidden from lists and rejected on direct call
      Given a tool "debug" tagged with "internal"
      And the server is configured with disabled tags "internal"
      When a client requests the tool list
      Then "debug" does not appear
      When a client calls "debug" directly
      Then the client receives an error "Tool not found"

    Scenario: Denylist takes precedence over allowlist
      Given tools:
        | name              | tags               |
        | public_search     | public             |
        | deprecated_search | public, deprecated |
        | internal_debug    | internal           |
      And the server is configured with enabled tags "public" and disabled tags "deprecated"
      When a client requests the tool list
      Then "public_search" appears
      And "deprecated_search" does not appear because the denylist overrides the allowlist
      And "internal_debug" does not appear because it is not in the allowlist

  Rule: Denylist filtering applies to resources

    Scenario: Resource with non-matching tags is hidden by the allowlist
      Given a resource "config://premium" tagged with "premium"
      And the server is configured with enabled tags "free"
      When a client requests the resource list
      Then the premium resource does not appear

  Rule: Tags are available in the operation context

    Scenario: A guard can read tool tags from the operation context
      Given a tool "search_emails" tagged with "email" and "premium"
      And a guard that inspects the operation tags
      When a client calls "search_emails"
      Then the guard can read tags "email" and "premium" from the context

  Rule: Runtime dynamic tag changes

    Scenario: Disabling a tag at runtime hides the tool and notifies clients
      Given a tool tagged with "experimental" that is currently visible
      And a connected client session
      When the "experimental" tag is disabled at runtime for the session
      Then the client receives a tool list changed notification
      And subsequent tool list requests no longer include the experimental tool

    Scenario: Enabling a tag at runtime reveals the tool for that session only
      Given the server is configured with enabled tags "basic"
      And a tool tagged with "premium" that is not visible
      When the "premium" tag is enabled at runtime for a specific session
      Then that session's tool list now includes the premium tool
      And other sessions still do not see the premium tool

  Rule: Tag-based scope requirements (TagScopeGuard)

    Scenario: Tool with a scope-mapped tag rejects callers missing the required scope
      Given the server maps tag "admin" to required scope "admin:write"
      And a tool "delete_user" tagged with "admin"
      When a caller with scope "user:read" calls "delete_user"
      Then the call is rejected for insufficient permissions
      When a caller with scope "admin:write" calls "delete_user"
      Then the call succeeds

    Scenario: Tool without scope-mapped tags is unaffected by the tag scope guard
      Given the server maps tag "admin" to required scope "admin:write"
      And a tool "search_emails" tagged with "email"
      When a caller with scope "user:read" calls "search_emails"
      Then the call succeeds because "email" has no scope requirement

    Scenario: Multiple scope-mapped tags require the union of all scopes
      Given the server maps tag "admin" to scope "admin:write" and tag "sensitive" to scope "data:read"
      And a tool "export_user_data" tagged with "admin" and "sensitive"
      When a caller with only scope "admin:write" calls "export_user_data"
      Then the call is rejected because "data:read" is also required
      When a caller with scopes "admin:write" and "data:read" calls "export_user_data"
      Then the call succeeds

    Scenario: Tag scope guard hides tools at list time
      Given the server maps tag "admin" to required scope "admin:write"
      And a tool "delete_user" tagged with "admin"
      When a caller with scope "user:read" requests the tool list
      Then "delete_user" does not appear
      When a caller with scope "admin:write" requests the tool list
      Then "delete_user" appears
```

## FastMCP Parity
FastMCP (Python) supports:
- `tags` parameter on tool/resource/prompt definitions — our `tags: string[]` option on `@Tool()`, `@Resource()`, and `@Prompt()` mirrors this
- `mcp.enable(tags={"public"}, only=True)` — our `enabledTags` in `McpModule.forRoot()`
- `mcp.disable(tags={"internal"})` — our `disabledTags` in `McpModule.forRoot()`
- `restrict_tag("admin", require_scopes("admin:*"))` — our `tagScopes` + `TagScopeGuard`
- Combined enable/disable — our combined `enabledTags` + `disabledTags` with deny-wins precedence

Our implementation extends FastMCP's approach with:
- NestJS-idiomatic global configuration via `McpModule.forRoot()`
- Runtime dynamic changes via `McpSessionService` with list-changed notifications
- `TagScopeGuard` integrated into the standard NestJS guard chain
- Per-session tag overrides layered on global config

## Dependencies
- **Depends on:** CORE-001 (@Tool decorator) — decorator metadata must support `tags`
- **Depends on:** CORE-002 (@Resource decorator) — same for resources
- **Depends on:** CORE-003 (@Prompt decorator) — same for prompts
- **Depends on:** CORE-005 (Handler registry) — registry must filter by tags during list operations; tag metadata stored in `RegistryEntry`
- **Depends on:** AUTH-001 (McpAuthModule) — `TagScopeGuard` requires identity/scopes from auth layer
- **Depends on:** CORE-013 (Handlers) — list-time filtering by `TagScopeGuard` requires handler integration
- **Depends on:** SDK-005 (List change notifications) — runtime tag changes trigger list-changed notifications
- **Blocks:** SDK-007 — session-scoped visibility builds on top of server-level tag filtering

## Technical Notes
- To apply `TagScopeGuard` globally, register it as `{ provide: APP_GUARD, useClass: McpOnly(TagScopeGuard) }` in any module's providers — standard NestJS global guard registration
- Store tags in decorator metadata: `Reflect.defineMetadata('mcp:tags', tags, target, propertyKey)`
- During list handler registration, filter items based on `enabledTags` and `disabledTags` config
- For dynamic filtering, evaluate the filter function at request time (not at registration time) to support runtime changes
- Tags in `_meta` field of MCP responses:
  ```typescript
  { name: 'search_emails', description: '...', inputSchema: {...}, _meta: { tags: ['email', 'read'] } }
  ```
- The `meta` option on `@Tool()` (from the design artifact) already supports arbitrary `_meta` — tags could be sugar that sets `_meta.tags`. But keep them as a first-class option for ergonomics and to enable the `enabledTags`/`disabledTags` filtering features.
- Tag filtering order: `disabledTags` check runs first (deny), then `enabledTags` check (allow). If a component is denied, it is never shown regardless of allowlist.
- `TagScopeGuard` implementation:
  ```typescript
  @Injectable()
  export class TagScopeGuard implements CanActivate {
    constructor(
      @Inject(MCP_MODULE_OPTIONS) private options: McpModuleOptions,
      private registry: McpRegistryService,
    ) {}

    canActivate(context: ExecutionContext): boolean {
      if (context.getType() !== 'mcp') return true;
      const mcpCtx = context.switchToMcp().getMcpContext();
      const tags = mcpCtx.tags ?? [];
      const tagScopes = this.options.tagScopes ?? {};
      const requiredScopes = tags.flatMap(tag => tagScopes[tag] ?? []);
      if (requiredScopes.length === 0) return true;
      const identity = mcpCtx.identity;
      return requiredScopes.every(scope => identity?.scopes?.includes(scope));
    }
  }
  ```
- Session-level tag state stored in `McpSessionService` per session ID, merged with global config at query time
- Runtime `disableTags`/`enableTags` calls should debounce list-changed notifications (avoid flooding if multiple tag changes happen in quick succession)
