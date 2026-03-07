# CORE-009: McpExecutionContextHost + switchToMcp()

## Summary
Implement `McpExecutionContextHost` (extends NestJS `ExecutionContextHost` with `contextType = 'mcp'`), the `McpArgumentsHost` interface, `switchToMcp()` via TypeScript module augmentation on `ArgumentsHost`, and the `McpOnly(guard)` wrapper utility for hybrid HTTP+MCP applications.

## Background / Context
NestJS uses `ExecutionContextHost` internally for HTTP, WebSocket (`switchToWs()`), and RPC (`switchToRpc()`) contexts. The MCP framework follows the same pattern to integrate with NestJS's guard/interceptor/pipe infrastructure. This allows standard `CanActivate` guards to detect MCP context via `context.getType() === 'mcp'` and access MCP-specific data via `context.switchToMcp()`.

The `McpOnly(guard)` wrapper is sugar for hybrid apps that have both HTTP controllers and MCP tools registered in the same NestJS application — it prevents MCP-specific guards from running (and failing) on HTTP requests.

## Acceptance Criteria
- [ ] `McpExecutionContextHost` extends `ExecutionContextHost` from `@nestjs/core`
- [ ] `context.getType()` returns `'mcp'`
- [ ] `context.switchToMcp()` returns `McpArgumentsHost`
- [ ] `McpArgumentsHost.getMcpContext()` returns `McpOperationContext`
- [ ] `McpArgumentsHost.getInput()` returns `Record<string, unknown>` (the validated tool/prompt arguments)
- [ ] `McpOperationContext` interface has: `type`, `name`, `args`, `identity` (McpIdentity | null), `sessionId` (string | null), `extras` (Map), `httpRequest` (available in pipeline, NOT on McpContext)
- [ ] TypeScript module augmentation adds `switchToMcp()` to `@nestjs/common`'s `ArgumentsHost` interface
- [ ] `McpOnly(guard)` function takes a guard class, returns a new guard class that passes through for non-MCP contexts
- [ ] `McpExecutionContextHost.createForList(handlerRef, handlerName, contextType)` — a variant factory method for constructing execution contexts for list operations (listTools, listResources, listPrompts). Unlike `create()` which wraps a full tool/resource/prompt invocation, `createForList()` creates a lightweight context suitable for guard/filter checks during list-time filtering. The `McpContext` injected during list operations does NOT have `args` or `progress` — only `identity`, `session`, and `server`.
- [ ] All interfaces and classes exported from `@unique-ag/nestjs-mcp`

## BDD Scenarios

```gherkin
Feature: MCP execution context integrates with NestJS guard/interceptor infrastructure

  Rule: MCP context type is distinguishable from HTTP and WebSocket

    Scenario: Execution context reports "mcp" as its type
      Given a guard running during an MCP tool call
      When the guard checks the context type
      Then the type is "mcp"

  Rule: switchToMcp() provides access to MCP-specific data

    Scenario: Guard accesses the MCP operation context
      Given a guard running during a tool call named "search" by an authenticated user
      When the guard switches to the MCP context
      Then it can read the operation type as "tool"
      And it can read the operation name as "search"
      And it can read the user's identity

    Scenario: Guard accesses the validated tool input
      Given a guard running during a tool call with argument query "test"
      When the guard switches to the MCP context and reads the input
      Then it receives the argument query "test"

    Scenario: Session ID is available in the operation context
      Given a guard running during a tool call in session "sess-abc-123"
      When the guard switches to the MCP context
      Then the session ID is "sess-abc-123"

    Scenario: Identity is null for unauthenticated requests
      Given a guard running during an unauthenticated MCP tool call
      When the guard switches to the MCP context
      Then the identity is null

  Rule: McpOnly wrapper skips MCP guards for non-MCP requests

    Scenario: MCP-specific guard is skipped for HTTP requests
      Given a scope guard wrapped with McpOnly and applied globally
      And an incoming HTTP request
      When the guard runs
      Then the request is allowed through without invoking the scope guard

    Scenario: MCP-specific guard is invoked for MCP requests
      Given a scope guard wrapped with McpOnly and applied globally
      And an incoming MCP tool call
      When the guard runs
      Then the scope guard logic is executed
      And its result determines whether the call is allowed

    Scenario: McpOnly guard with dependencies resolves them via dependency injection
      Given a scope guard that depends on ConfigService, wrapped with McpOnly
      And registered as a global guard
      When the application starts
      Then the scope guard receives its ConfigService dependency

  Rule: List-time context provides identity but no args

    Scenario: List-time context has identity but no args
      Given a guard running during a listTools request by an authenticated user
      When the guard switches to the MCP context created via createForList()
      Then the identity is present with the session user's information
      And the operation type matches the handler's component type
      And the operation name matches the handler's registered name
      And getInput() returns an empty record
      And the McpContext does not provide args or progress

  Rule: Module augmentation makes switchToMcp() available on all contexts

    Scenario: TypeScript recognizes switchToMcp() on ExecutionContext
      Given a TypeScript file that imports from "@unique-ag/nestjs-mcp"
      When the file calls switchToMcp() on an ExecutionContext
      Then the code compiles without type errors
      And the return type provides getMcpContext() and getInput() methods
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-005 — registry entries provide class/method refs for ExecutionContext
- Blocks: CORE-006 — getMcpIdentity helper uses switchToMcp()
- Blocks: CORE-010 — pipeline runner creates McpExecutionContextHost
- Blocks: CORE-011 — built-in guards use switchToMcp()

## Interface Contract
Consumed by CORE-006 (getMcpIdentity), CORE-010 (pipeline runner), CORE-011 (built-in components):
```typescript
export interface McpArgumentsHost {
  getMcpContext(): McpOperationContext;
  getInput(): Record<string, unknown>;
}

export interface McpOperationContext {
  readonly type: 'tool' | 'resource' | 'resource-template' | 'prompt';
  readonly name: string;
  readonly args: Record<string, unknown>;
  readonly identity: McpIdentity | null;
  readonly sessionId: string | null;
  readonly extras: Map<string, unknown>;
  readonly httpRequest: HttpRequest | null;
}

export class McpExecutionContextHost extends ExecutionContextHost {
  switchToMcp(): McpArgumentsHost;
  getType(): 'mcp';
}

export function McpOnly(guard: Type<CanActivate>): Type<CanActivate>;
```

## Technical Notes
- Module augmentation (from design artifact):
  ```typescript
  declare module '@nestjs/common' {
    interface ArgumentsHost {
      switchToMcp(): McpArgumentsHost;
    }
  }
  ```
  This must be in a `.d.ts` file or a file with `export {}` to be treated as a module augmentation.
- `McpExecutionContextHost` constructor should accept: `args: unknown[]`, `classRef: Type`, `handler: Function`, `mcpOperationContext: McpOperationContext`
- The `switchToMcp()` method is added to the prototype of `ExecutionContextHost` at module load time (side effect import)
- `McpOnly` implementation (from design artifact):
  ```typescript
  export function McpOnly(guard: Type<CanActivate>): Type<CanActivate> {
    @Injectable()
    class McpOnlyGuard implements CanActivate {
      constructor(private readonly inner: InstanceType<typeof guard>) {}
      canActivate(context: ExecutionContext) {
        if (context.getType() !== 'mcp') return true;
        return this.inner.canActivate(context);
      }
    }
    return mixin(McpOnlyGuard);
  }
  ```
  `mixin` is from `@nestjs/common` — it ensures proper DI resolution.
- File locations:
  - `packages/nestjs-mcp/src/context/mcp-execution-context-host.ts`
  - `packages/nestjs-mcp/src/context/mcp-arguments-host.interface.ts`
  - `packages/nestjs-mcp/src/context/mcp-operation-context.interface.ts`
  - `packages/nestjs-mcp/src/context/switch-to-mcp.augmentation.ts`
  - `packages/nestjs-mcp/src/helpers/mcp-only.ts`
