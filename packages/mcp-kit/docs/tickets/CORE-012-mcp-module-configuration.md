# CORE-012: McpModule configuration

## Summary
Implement `McpModule.forRoot()` and `McpModule.forRootAsync()` that configure the MCP framework, register all internal services, discover tool/resource/prompt classes, and wire the `ExternalContextCreator` pipeline. This is the main entry point consumers use to enable MCP in their NestJS application.

## Background / Context
`McpModule` is the main entry point consumers use to enable MCP in their NestJS application. It provides `forRoot()` and `forRootAsync()` with:
- `sessionStore`, `sessionTtlMs` for session persistence
- `streamableHttp` config object for Streamable HTTP transport options
- Transport config (Streamable HTTP is the default)
- Internal services wired: `McpHandlerRegistry`, `McpPipelineRunner`, `McpIdentityResolver`, handlers

## Acceptance Criteria
- [ ] `McpModule.forRoot(options: McpOptions)` returns a `DynamicModule`
- [ ] `McpModule.forRootAsync(options: McpModuleAsyncOptions)` returns a `DynamicModule`
- [ ] `McpOptions` interface includes: `name` (required), `version` (required), `instructions` (optional), `sessionStore` (optional, defaults to InMemorySessionStore), `sessionTtlMs` (optional, defaults to 24h), `streamableHttp` config (optional)
- [ ] Registers `McpHandlerRegistry` as singleton provider
- [ ] Registers `McpPipelineRunner` as singleton provider
- [ ] Registers `McpIdentityResolver` as REQUEST-scoped provider
- [ ] Registers `McpToolsHandler`, `McpResourcesHandler`, `McpPromptsHandler`
- [ ] Registers `MCP_OPTIONS` injection token with resolved options
- [ ] Imports `DiscoveryModule` for handler discovery
- [ ] `forRootAsync` supports `useFactory`, `useClass`, `useExisting` patterns
- [ ] `forRootAsync` supports `inject` for dependency injection into factory
- [ ] `maskErrorDetails` option (optional `boolean`, default `false`) — module-wide default for masking internal error details from clients. Per-tool `mask: true` in `@Tool()` options takes precedence over the module-level `maskErrorDetails` setting. If a tool has `mask: false` explicitly, it overrides `maskErrorDetails: true` on the module. The default when `mask` is omitted is to inherit from `maskErrorDetails` (which defaults to `false`)
- [ ] `onDuplicate` option (optional, `'warn' | 'error' | 'replace' | 'ignore'`, default `'warn'`) — behavior when two tools/resources/prompts register the same name. `'warn'` logs and keeps first, `'error'` throws at boot, `'replace'` keeps last, `'ignore'` keeps first silently. Handler registry (CORE-005) must respect this setting
- [ ] `listPageSize` option (optional `number`, default `undefined`) — pagination limit for `listTools`/`listResources`/`listPrompts` responses. When set, responses include a `nextCursor` for pagination. `undefined`/`null` returns all items (no pagination)
- [ ] `serverInfo` option (optional `{ websiteUrl?: string; icons?: ServerIcon[] }`) — additional server metadata forwarded in the MCP `initialize` response
- [ ] `websiteUrl` included in server metadata sent during MCP initialization handshake
- [ ] `icons` included in server metadata sent during MCP initialization handshake
- [ ] `strictInputValidation: true` → tool called with `"10"` for an integer param returns InvalidParams error
- [ ] `strictInputValidation: false` (default) → `"10"` coerced to `10` for integer param
- [ ] `derefSchemas: true` (default) → listTools returns schemas with `$ref` inlined (links to CORE-025)
- [ ] Missing `name` or `version` in options throws at boot with descriptive error
- [ ] Module exports `McpHandlerRegistry` and `McpSessionService` (for consumer access)

## BDD Scenarios

```gherkin
Feature: MCP Module Configuration
  McpModule.forRoot() and McpModule.forRootAsync() configure the MCP server,
  register internal services, and control module-wide behaviors like error
  masking, duplicate handling, pagination, and input validation.

  Rule: Basic module initialization

    Scenario: Minimal configuration bootstraps successfully
      Given the MCP module is configured with name "my-mcp" and version "1.0.0"
      When the application starts
      Then the module initializes without error
      And the server reports name "my-mcp" and version "1.0.0"
      And sessions are stored in memory by default

    Scenario: Async configuration via factory
      Given the MCP module is configured asynchronously using a factory that reads from environment config
      When the application starts
      Then the factory is called with the injected config service
      And the server name and version are set from the factory result

    Scenario: Missing required name or version causes a startup error
      Given the MCP module is configured without a version
      When the application starts
      Then a descriptive error is thrown mentioning the missing "version" field

    Scenario: Async configuration via options class
      Given the MCP module is configured asynchronously using an options class
      When the application starts
      Then the options class is instantiated via dependency injection
      And its factory method is called to produce the configuration

  Rule: Custom session store

    Scenario: Custom session store receives session data
      Given the MCP module is configured with a Redis-backed session store
      When a new MCP session is created
      Then the session data is persisted through the Redis session store

  Rule: Module exports

    Scenario: Handler registry and session service are available to other modules
      Given the MCP module is configured
      When another module requests the handler registry
      Then the registry instance is provided
      When another module requests the session service
      Then the session service instance is provided

  Rule: Error masking

    Scenario: Module-wide error masking hides internal error details
      Given the MCP module is configured with error masking enabled
      And a tool throws an error with message "secret database credentials invalid"
      When the client receives the error response
      Then the response contains "Internal server error" instead of the original message

    Scenario: Per-tool mask override exposes error details despite module masking
      Given the MCP module is configured with error masking enabled
      And a tool is configured to show error details
      And that tool throws an error with message "visible error"
      When the client receives the error response
      Then the response contains "visible error"

  Rule: Duplicate name handling

    Scenario Outline: Duplicate tool names are handled per configuration
      Given the MCP module is configured with duplicate handling set to "<mode>"
      And two tools are registered with the name "search"
      When the application starts
      Then <outcome>

      Examples:
        | mode    | outcome                                                        |
        | warn    | a warning is logged and the first registration is kept         |
        | error   | a startup error is thrown mentioning duplicate "search"        |
        | replace | no error is thrown and the second registration replaces the first |

  Rule: List pagination

    Scenario: Page size limits the number of items per list response
      Given the MCP module is configured with a list page size of 10
      And 25 tools are registered
      When a client requests the tool list without a cursor
      Then the response contains 10 tools and a pagination cursor
      When the client requests the tool list with the returned cursor
      Then the response contains the next 10 tools

    Scenario: No page size returns all items in a single response
      Given the MCP module is configured without a list page size
      And 25 tools are registered
      When a client requests the tool list
      Then the response contains all 25 tools with no pagination cursor

  Rule: Input validation strictness

    Scenario: Strict validation rejects type-mismatched input
      Given the MCP module is configured with strict input validation enabled
      And a tool accepts an integer parameter "count"
      When a client calls the tool with count as the string "10"
      Then the client receives an InvalidParams error
      And the tool handler is not invoked

    Scenario: Lenient validation coerces compatible types by default
      Given the MCP module is configured with default settings
      And a tool accepts an integer parameter "count"
      When a client calls the tool with count as the string "10"
      Then the value is coerced to the number 10
      And the tool handler receives count as 10

  Rule: Server metadata in initialization

    Scenario: Server info is included in the initialization handshake
      Given the MCP module is configured with a website URL and server icon
      When a client sends an initialization request
      Then the server response includes the website URL and icon metadata
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-005 — McpHandlerRegistry (registered as provider)
- Depends on: CORE-006 — McpIdentityResolver (registered as REQUEST-scoped provider)
- Depends on: CORE-010 — McpPipelineRunner (registered as provider)
- Depends on: CORE-011 — built-in pipeline components (registered as opt-in providers)
- Blocks: CORE-013 — handlers depend on module wiring
- Blocks: AUTH-001 — auth module imports from core module
- Blocks: CORE-016 — server composition extends module config
- Blocks: TEST-001 — testing module wraps McpModule

## Technical Notes
- Use a `__isMcpModule` marker property on the dynamic module — the registry uses it to find which modules imported McpModule
- `McpOptions` interface:
  ```typescript
  interface McpOptions {
    name: string;
    version: string;
    instructions?: string;
    capabilities?: ServerCapabilities;
    sessionStore?: McpSessionStore;
    sessionTtlMs?: number;
    maskErrorDetails?: boolean;                          // module-wide error masking default (FastMCP parity)
    onDuplicate?: 'warn' | 'error' | 'replace' | 'ignore'; // duplicate name behavior (default: 'warn')
    listPageSize?: number;                               // pagination limit for list responses
    websiteUrl?: string;                                   // URL to info about server, included in server metadata
    icons?: Array<{ url: string; mediaType: string }>;     // visual identifiers for the server
    strictInputValidation?: boolean;                       // default false; when true rejects type coercions ("10" for int param)
    derefSchemas?: boolean;                                // default true; auto-dereference $ref in generated JSON schemas
    serverInfo?: {                                         // additional server metadata; websiteUrl/icons are shorthand aliases
      websiteUrl?: string;
      icons?: Array<{ url: string; mediaType: string }>;
    };
    transport?: McpTransportType | McpTransportType[];
    streamableHttp?: {
      statelessMode?: boolean;
      sessionIdGenerator?: () => string;
      enableJsonResponse?: boolean;
    };
    sse?: { pingEnabled?: boolean; pingIntervalMs?: number; };
    sseEndpoint?: string;
    messagesEndpoint?: string;
    mcpEndpoint?: string;
    apiPrefix?: string;
  }
  ```
- To apply guards/interceptors/pipes to MCP handlers, use standard NestJS `APP_GUARD`/`APP_INTERCEPTOR`/`APP_PIPE` global providers combined with the `McpOnly()` wrapper from CORE-009 (ensures they only fire for MCP contexts)
- The `forRootAsync` pattern follows the same structure as the existing module but adds the new options
- Module ID generation (`mcp-module-${counter}`) for multi-module support should be preserved
- **Cross-references:** `onDuplicate` requires CORE-005 (handler registry) to check for duplicate names during registration and respect the configured behavior. `listPageSize` affects CORE-013 handlers (they must implement cursor-based pagination when set). `maskErrorDetails` is consumed by CORE-010 (pipeline runner) as the default, overridden by per-tool `mask` from CORE-001. `serverInfo` is forwarded to the SDK `McpServer` constructor or `initialize` response handler
- **`websiteUrl`/`icons` vs `serverInfo` precedence**: `websiteUrl` and `icons` are top-level shorthand options that set the corresponding fields in `serverInfo`. If both `serverInfo.websiteUrl` and top-level `websiteUrl` are provided, `serverInfo.websiteUrl` wins (nested takes precedence over shorthand). Same for `icons`. This avoids ambiguity when both forms are used.
- **FastMCP parity:** `maskErrorDetails` maps to FastMCP's `mask_error_details` server option. `onDuplicate` maps to FastMCP's `on_duplicate_tools`/`on_duplicate_resources`/`on_duplicate_prompts`. `serverInfo.icons` / `icons` maps to FastMCP's `server_icon`. `listPageSize` is a framework addition (FastMCP does not paginate list responses). `strictInputValidation` maps to FastMCP's `strict_input_validation`. `derefSchemas` maps to FastMCP's `deref_schemas`. `websiteUrl` maps to FastMCP's `website_url`
- File location: `packages/nestjs-mcp/src/mcp.module.ts`
