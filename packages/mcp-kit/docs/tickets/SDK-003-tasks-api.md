# SDK-003: Tasks API -- @Tool({ longRunning: true })

## Summary
Expose the MCP SDK's experimental Tasks API through a `@Tool({ longRunning: true })` decorator option. Long-running tools return a task ID immediately, allow clients to poll for progress, and eventually deliver results. The framework handles task lifecycle, storage, and progress reporting transparently.

## Background / Context
The MCP SDK v1.25.2 includes an experimental Tasks API for long-running tool operations. Instead of blocking the client until completion, a long-running tool:
1. Returns a task ID immediately
2. Executes asynchronously in the background
3. Allows clients to poll for status/progress
4. Delivers the final result when complete

The SDK provides `registerTool({ taskSupport: 'optional' | 'required' })`, `ToolTaskHandler` interface, and `TaskStore` (with an in-memory implementation). Our framework should make this transparent to tool authors — they write a normal async method, and the framework handles the task wrapping.

## Acceptance Criteria
- [ ] `@Tool({ longRunning: true })` registers the tool with `taskSupport: 'optional'` in the SDK
- [ ] `@Tool({ longRunning: 'required' })` registers with `taskSupport: 'required'`
- [ ] Tool handler executes asynchronously after returning the task ID to the client
- [ ] `McpContext` gains `reportProgress(current: number, total: number, message?: string)` for long-running tools (updates task progress)
- [ ] Client can poll task status and receive progress updates
- [ ] When the tool handler resolves, the task is marked complete with the serialized result
- [ ] When the tool handler rejects, the task is marked failed with the error
- [ ] `InMemoryTaskStore` is used by default
- [ ] Custom task store can be provided via `McpModule.forRoot({ taskStore: { provide: MCP_TASK_STORE, useClass: RedisTaskStore } })`
- [ ] Task TTL is configurable (`McpModule.forRoot({ taskTtlMs: 3600000 })`)
- [ ] Tasks are cleaned up after TTL expiration

## BDD Scenarios

```gherkin
Feature: Long-running tools via Tasks API
  Tools marked as long-running return a task ID immediately,
  execute asynchronously, and allow clients to poll for progress and results.

  Background:
    Given an MCP server with the Tasks API enabled

  Rule: Long-running tools return task IDs and execute asynchronously

    Scenario: Client receives a task ID immediately when calling a long-running tool
      Given a registered long-running tool "generate_report"
      When an MCP client calls "generate_report"
      Then the response contains a task ID
      And the tool begins executing in the background

    Scenario: Regular tools execute synchronously without creating tasks
      Given a registered tool "quick_search" that is not long-running
      When an MCP client calls "quick_search"
      Then the result is returned directly
      And no task ID is created

  Rule: Clients can poll task status and retrieve results

    Scenario: Client polls a running task and sees progress
      Given an MCP client called "generate_report" and received task ID "task-001"
      And the tool has reported progress 50 out of 100 items with message "Processing item 50/100"
      When the client polls for task "task-001"
      Then the status is "running" with progress 50 of 100

    Scenario: Client retrieves the result of a completed task
      Given an MCP client called "generate_report" and received task ID "task-001"
      And the tool has finished executing successfully
      When the client polls for task "task-001"
      Then the status is "completed"
      And the task result contains the tool's output

    Scenario: Client sees failure details when a task errors
      Given an MCP client called "generate_report" and received task ID "task-002"
      And the tool threw an error "External API timeout"
      When the client polls for task "task-002"
      Then the status is "failed"
      And the error message contains "External API timeout"

  Rule: Tasks can be polled across sessions

    Scenario: A different session polls for a task created by another session
      Given session "s1" called "generate_report" and received task ID "task-004"
      When session "s2" polls for task "task-004"
      Then the task status is returned successfully

  Rule: Tasks respect TTL and cancellation

    Scenario: Task times out after configured TTL
      Given the MCP module is configured with a task TTL of 5000ms
      And an MCP client called a long-running tool and received a task ID
      When the tool has not completed after 5000ms
      Then the task status becomes "failed" with a timeout error

    Scenario: Client cancels a running task
      Given an MCP client called "generate_report" and received task ID "task-003"
      When the client cancels the request
      Then the tool's abort signal fires
      And the task status becomes "cancelled"

  Rule: Task storage is pluggable

    Scenario: Tasks use in-memory storage by default
      Given an MCP server with default configuration
      When an MCP client calls a long-running tool
      Then the task state is stored in memory

    Scenario: Custom task store receives task state
      Given the MCP module is configured with a custom Redis-based task store
      When an MCP client calls a long-running tool
      Then the task state is persisted via the custom store
```

## FastMCP Parity
FastMCP (Python) does not currently expose the Tasks API (it is experimental in the MCP SDK). Our implementation is ahead of FastMCP here, providing first-class long-running tool support via `@Tool({ longRunning: true })`. The SDK's experimental `ToolTaskHandler` and `TaskStore` interfaces are wrapped transparently.

## Dependencies
- **Depends on:** CORE-001 (@Tool decorator) — `longRunning` option on decorator metadata
- **Depends on:** CORE-013 (McpToolsHandler) — handler must detect `longRunning` and register with `taskSupport` in the SDK
- **Blocks:** none

## Technical Notes
- SDK types: `ToolTaskHandler`, `TaskStore`, `InMemoryTaskStore`, task metadata (TTL, poll intervals)
- The SDK's `registerTool()` with `taskSupport` option handles the protocol-level task creation and polling
- The framework's role is to:
  1. Detect `longRunning` in decorator metadata
  2. Pass `taskSupport` to SDK's `registerTool()`
  3. Wrap the tool handler to work with the `ToolTaskHandler` interface
  4. Map `ctx.reportProgress()` to the task's progress reporting mechanism
- `InMemoryTaskStore` from the SDK can be used as default; for production, consumers provide their own
- The `ToolTaskHandler` interface from the SDK:
  ```typescript
  interface ToolTaskHandler {
    createTask(params): Promise<{ taskId: string }>;
    getTask(taskId: string): Promise<TaskStatus>;
    getTaskResult(taskId: string): Promise<ToolResult>;
  }
  ```
- Task store is registered via standard NestJS provider token `MCP_TASK_STORE` — consumers pass a standard provider definition to `forRoot()` using `useClass`/`useFactory`/`useValue` syntax:
  ```typescript
  McpModule.forRoot({
    taskStore: { provide: MCP_TASK_STORE, useClass: RedisTaskStore },
  })
  // or with factory:
  McpModule.forRoot({
    taskStore: { provide: MCP_TASK_STORE, useFactory: (config: ConfigService) => new RedisTaskStore(config), inject: [ConfigService] },
  })
  ```
- The experimental nature of the Tasks API should be documented — API may change in future SDK versions
