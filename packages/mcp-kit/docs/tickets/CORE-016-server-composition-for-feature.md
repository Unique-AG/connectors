# CORE-016: Server composition (McpModule.forFeature)

## Summary
Implement `McpModule.forFeature()` to allow NestJS feature modules to register their own tools, resources, and prompts with optional name prefixing and namespacing. This enables modular MCP server composition where different feature modules contribute capabilities independently, following the standard NestJS `forRoot` / `forFeature` pattern. Includes prefix rules for tools, resources, and prompts, tag filter inheritance from parent, and configurable conflict resolution.

## Background / Context
In NestJS, `TypeOrmModule.forRoot()` sets up the global connection while `TypeOrmModule.forFeature([Entity])` registers entities per module. We apply the same pattern: `McpModule.forRoot()` configures the MCP server, and `McpModule.forFeature()` registers tools/resources/prompts from feature modules.

This is particularly useful for:
- Large applications where tools are organized across multiple modules (email tools, calendar tools, file tools)
- Reusable tool libraries that can be imported as NestJS modules
- Name prefixing to avoid collisions between feature modules

FastMCP (Python) supports server composition via `server.mount(child, prefix="weather")` which mounts a sub-application under a prefix. Our approach uses NestJS's native module system instead, achieving the same result with better DI integration.

## Acceptance Criteria

### Core forFeature
- [ ] `McpModule.forFeature()` is a static module method that registers tools/resources/prompts from the importing module
- [ ] `McpModule.forFeature()` without prefix registers tools with their original names
- [ ] Multiple `forFeature()` modules can coexist in the same application
- [ ] Tools from `forFeature()` modules are included in `listTools` responses alongside `forRoot` tools
- [ ] Resources from `forFeature()` modules are included in `listResources`
- [ ] Prompts from `forFeature()` modules are included in `listPrompts`
- [ ] `forFeature()` modules respect global guards, interceptors, and pipes from `forRoot()`
- [ ] Global guards, interceptors, and pipes registered via `APP_GUARD`/`APP_INTERCEPTOR`/`APP_PIPE` in any module apply to all MCP components regardless of whether they were registered via `forRoot()` or `forFeature()`. This is standard NestJS global DI behavior — no special handling needed in `forFeature()`

### Prefix / Namespacing
- [ ] `McpModule.forFeature({ prefix: 'weather' })` prefixes all tool names with `weather_` (e.g., `get_forecast` becomes `weather_get_forecast`)
- [ ] Prompts are prefixed with kebab-case join: `{prefix}-{prompt-name}` (e.g., `forecast-summary` becomes `weather-forecast-summary`)
- [ ] Resources have prefix segment prepended to URI path: `files://docs/report` becomes `files://weather/docs/report`
- [ ] Prefix is stored in `RegistryEntry.prefix` field in the handler registry (CORE-005)
- [ ] Prefix transformation is applied at registration time, not at query time

### Tag filter inheritance
- [ ] Tag filters set on `McpModule.forRoot({ enabledTags: ['public'] })` apply to ALL components including those from `forFeature` modules
- [ ] Tag filters set on `McpModule.forRoot({ disabledTags: ['internal'] })` also apply to all `forFeature` components
- [ ] Components registered via `forFeature` without the required tags are excluded from lists (same filtering logic as root-level components)

### Conflict resolution
- [ ] `onDuplicate` is configured once in `McpModule.forRoot()` and applies globally to all registrations from all feature modules
- [ ] When `onDuplicate: 'error'` (from CORE-012 config), `forFeature` registration with a conflicting name throws at module init time
- [ ] When `onDuplicate: 'replace'`, later registration silently replaces the earlier one
- [ ] When `onDuplicate: 'warn'` (default), later registration replaces with a warning log
- [ ] Collision detection considers the final prefixed name, not the original name
- [ ] Two `forFeature()` calls with the same `prefix` do NOT cause an error — the prefix is just a naming convention. Name collision rules (`onDuplicate`) apply to the final resolved names, not the prefixes themselves

## BDD Scenarios

```gherkin
Feature: Server Composition via forFeature
  Feature modules register their own tools, resources, and prompts with
  optional name prefixing. Components from all feature modules appear
  alongside root-level components in list responses.

  Rule: Feature module components appear in list responses

    Scenario: Tool from a feature module appears in the tool list
      Given an email module registers tool "search_emails" via forFeature
      When a client requests the tool list
      Then "search_emails" appears in the response

    Scenario: Multiple feature modules contribute tools to the same server
      Given an email module contributes 3 tools via forFeature
      And a calendar module contributes 2 tools via forFeature
      And a files module contributes 4 tools via forFeature
      When a client requests the tool list
      Then all 9 tools appear in the response

    Scenario: Prompts from a feature module appear in the prompt list
      Given an email module registers prompt "draft-reply" via forFeature
      When a client requests the prompt list
      Then "draft-reply" appears in the response

    Scenario: Resources from a feature module appear in the resource list
      Given an email module registers resource "inbox://messages" via forFeature with prefix "email"
      When a client requests the resource list
      Then a resource with URI "inbox://email/messages" appears in the response

  Rule: Prefix namespacing prevents collisions

    Scenario: Prefixed tool names avoid collisions between modules
      Given an email module with prefix "email" registers tool "search"
      And a calendar module with prefix "calendar" registers tool "search"
      When a client requests the tool list
      Then "email_search" and "calendar_search" both appear
      And there is no name collision

    Scenario: Prompts are prefixed with kebab-case
      Given a weather module with prefix "weather" registers prompt "forecast-summary"
      When a client requests the prompt list
      Then "weather-forecast-summary" appears in the response

    Scenario: Resource URIs include the prefix as a path segment
      Given a weather module with prefix "weather" registers resource "data://forecast/today"
      When a client requests the resource list
      Then a resource with URI "data://weather/forecast/today" appears

    Scenario: No prefix preserves original names
      Given an email module registers tool "search_emails" via forFeature without a prefix
      When a client requests the tool list
      Then "search_emails" appears with its original name

  Rule: Name collision resolution

    Scenario: Collision with error mode throws at startup
      Given the server is configured with duplicate handling set to "error"
      And an email module with prefix "mail" registers tool "search" (resolved name "mail_search")
      And a calendar module registers tool "mail_search" without a prefix
      When the application starts
      Then an error is thrown mentioning a name collision for "mail_search"

    Scenario: Collision with replace mode keeps the later registration
      Given the server is configured with duplicate handling set to "replace"
      And module A registers tool "search" via forFeature
      And module B registers tool "search" via forFeature after module A
      When the application starts
      Then no error is thrown
      And the "search" tool handler comes from module B

  Rule: forFeature requires forRoot

    Scenario: Using forFeature without forRoot causes a startup error
      Given an application imports forFeature without any forRoot configuration
      When the application starts
      Then an error is thrown indicating that forRoot must be imported first

  Rule: Tag filter inheritance from root configuration

    Scenario: Root-level allowlist applies to feature module tools
      Given the server is configured with enabled tags "public"
      And a weather module with prefix "weather" registers tool "get_forecast" tagged "public"
      And the weather module also registers tool "debug_info" tagged "internal"
      When a client requests the tool list
      Then "weather_get_forecast" appears
      And "weather_debug_info" does not appear

    Scenario: Root-level denylist applies to feature module tools
      Given the server is configured with disabled tags "deprecated"
      And a weather module with prefix "weather" registers tool "old_forecast" tagged "deprecated"
      When a client requests the tool list
      Then "weather_old_forecast" does not appear
```

## FastMCP Parity
FastMCP (Python) supports server composition via `mount()` which mounts a sub-application under a prefix:
- `server.mount(child)` — same-process composition (our `McpModule.forFeature()`)
- `server.mount(child, prefix="weather")` — namespaced composition (our `McpModule.forFeature({ prefix: 'weather' })`)
- Tag filters on parent apply recursively to mounted children (our tag filter inheritance)
- Conflict resolution: later-mounted server wins on name collision (our `onDuplicate: 'replace'` mode)

Our approach uses NestJS's native module system instead. The key difference is that FastMCP `mount()` composes separate server instances, while our approach uses a single server with a shared registry — more efficient and better integrated with NestJS DI.

## Dependencies
- **Depends on:** CORE-001 (@Tool decorator) — tools from feature modules use the same decorator
- **Depends on:** CORE-005 (Handler registry) — central registry must accept registrations from multiple modules; `RegistryEntry` needs `prefix` field
- **Depends on:** CORE-012 (McpModule.forRoot) — root module must exist and manage the central registry; forFeature is a companion static method on the same module class; `onDuplicate` config lives here
- **Blocks:** none

## Technical Notes
- Per-feature guards should be applied via `@UseGuards()` on the service class or individual methods within the feature module — no need for a custom `guards` option in `forFeature()`
- `McpModule.forFeature()` returns a `DynamicModule` that:
  1. Scans its parent module's providers for `@Tool`, `@Resource`, `@Prompt` decorated classes
  2. Registers discovered handlers with the central `McpRegistryService` (from `forRoot`)
  3. Applies prefix transformation if specified
- The `McpRegistryService` (singleton, from `forRoot`) maintains the master list of all tools/resources/prompts
- Prefix transformation rules:
  - Tools: `{prefix}_{toolName}` (snake_case join)
  - Prompts: `{prefix}-{promptName}` (kebab-case join, since prompts conventionally use kebab)
  - Resources: prepend prefix segment to URI path — `protocol://path` becomes `protocol://{prefix}/path`
- `RegistryEntry` (CORE-005) needs a `prefix?: string` field to track which prefix was applied, useful for debugging and introspection
- Name collision detection happens during `onModuleInit` — iterate all registered names, handle per `onDuplicate` setting
- Implementation pattern:
  ```typescript
  @Module({})
  export class McpModule {
    static forRoot(options: McpModuleOptions): DynamicModule { /* ... */ }

    static forFeature(options?: McpFeatureOptions): DynamicModule {
      return {
        module: McpModule,
        providers: [
          { provide: MCP_FEATURE_OPTIONS, useValue: options ?? {} },
          McpFeatureScanner,  // scans for @Tool/@Resource/@Prompt in the importing module
        ],
      };
    }
  }
  ```
- `McpFeatureScanner` uses `DiscoveryService` (from `@nestjs/core`) to find decorated providers within the importing module's scope
- `McpFeatureScanner` uses NestJS `DiscoveryService` to find providers decorated with `@Tool`/`@Resource`/`@Prompt` within the **importing module's providers array only** (direct providers, not transitively imported modules). If a feature module imports a sub-module that also has tools, those sub-module tools are NOT auto-discovered — the sub-module must also call `McpModule.forFeature()`
- Tag filter inheritance is automatic — `McpRegistryService` applies the same global `enabledTags`/`disabledTags` filters to all entries regardless of origin module. No special code needed; the filtering in CORE-015 operates on the unified registry.
