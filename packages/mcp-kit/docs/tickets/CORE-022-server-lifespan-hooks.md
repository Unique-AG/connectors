# CORE-022: Server lifespan / startup-teardown hooks

## Summary
Document how to hook into MCP server startup and teardown using standard NestJS lifecycle interfaces (`OnApplicationBootstrap`, `OnModuleDestroy`). No custom `lifespan` config option is needed — consumers create their own service.

## Background / Context
FastMCP supports `lifespan=async_context_manager` on the server constructor for setup/teardown orchestration. The lifespan context manager runs once when the server starts (after all tools/resources/prompts are registered) and provides a cleanup hook for when the server shuts down. Common uses: pre-loading resource caches, establishing upstream connections, background tool registration, graceful cleanup.

NestJS already has `OnApplicationBootstrap` / `OnModuleDestroy` lifecycle interfaces. Since `McpHandlerRegistry` populates during its own `onApplicationBootstrap`, any consumer service that injects it will have access to the fully populated registry by the time its own `onApplicationBootstrap` runs (NestJS initializes dependencies first). No custom `lifespan` config is needed.

## Acceptance Criteria
- [ ] Documentation and example show how to use `OnApplicationBootstrap` to run code after the MCP registry is fully populated
- [ ] Documentation shows how to use `OnModuleDestroy` for cleanup
- [ ] `McpHandlerRegistry` and `McpServer` are injectable into consumer services for use in lifecycle hooks
- [ ] Example shows injecting `McpHandlerRegistry` to verify ordering (registry initializes before consumer service bootstraps)

## BDD Scenarios

```gherkin
Feature: Server lifespan and startup-teardown hooks
  Developers can hook into the MCP server lifecycle to run setup
  and cleanup logic using standard NestJS lifecycle interfaces.

  Rule: Startup hooks run after the MCP registry is fully populated

    Scenario: Application startup hook can inspect registered tools
      Given a developer has created a lifecycle service that runs logic on application startup
      And the MCP server has tools "search" and "analyze" registered via decorators
      When the application starts up
      Then the startup hook runs after all MCP tools, resources, and prompts are registered
      And the startup hook can read the list of registered tools
      And the list includes "search" and "analyze"

    Scenario: Startup hook can register additional tools dynamically
      Given a developer has created a startup hook that registers a "warmup_cache" tool
      When the application starts up
      Then the "warmup_cache" tool is available to clients after startup completes

  Rule: Teardown hooks run when the application shuts down

    Scenario: Cleanup logic executes on application shutdown
      Given a developer has created a lifecycle service that closes database connections on shutdown
      And the application is running with active MCP sessions
      When the application receives a shutdown signal
      Then the cleanup logic runs before the process exits

  Rule: MCP server internals are injectable into lifecycle services

    Scenario: Lifecycle service can inject the MCP server and registry
      Given a developer has created a lifecycle service that depends on the MCP server and registry
      When the application starts up
      Then both the MCP server and registry are available in the lifecycle service
      And the registry is already fully initialized
```

## FastMCP Parity
- **FastMCP**: `lifespan=async_context_manager` — a Python async context manager that receives the server instance. `__aenter__` runs at startup, `__aexit__` runs at shutdown. Can yield a context dict accessible by tools.
- **NestJS**: Standard `OnApplicationBootstrap` / `OnModuleDestroy` lifecycle interfaces. Consumer injects `McpHandlerRegistry` and `McpServer` directly — no wrapper needed.
- **Difference**: FastMCP's lifespan can yield a shared context object; our approach uses the existing NestJS DI container for shared state. No custom abstraction layer is needed.

## Dependencies
- **Depends on:** CORE-012 — McpModule configuration (no new options needed, just exports)
- **Depends on:** CORE-005 — McpHandlerRegistry (must be injectable and populated during bootstrap)
- **Blocks:** nothing

## Technical Notes
- No custom `McpLifespanService` or `lifespan` config option is needed. Consumers implement lifecycle themselves:
  ```typescript
  // Consumer implements lifecycle themselves — no custom McpModule config needed:
  @Injectable()
  export class AppLifecycleService implements OnApplicationBootstrap, OnModuleDestroy {
    constructor(
      private readonly registry: McpHandlerRegistry,
      private readonly server: McpServer,
    ) {}

    async onApplicationBootstrap() {
      // MCP registry is fully populated here
      console.log('Tools registered:', this.registry.getTools().length);
    }

    async onModuleDestroy() {
      // cleanup
    }
  }
  ```
- Ordering is guaranteed by NestJS DI: since `AppLifecycleService` injects `McpHandlerRegistry`, NestJS initializes the registry (and runs its `onApplicationBootstrap`) before initializing the consumer service.
- `McpHandlerRegistry` and `McpServer` must be exported from `McpModule` so they are injectable in consumer modules.
