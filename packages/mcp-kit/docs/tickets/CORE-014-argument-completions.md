# CORE-014: Argument completions (@Complete decorator)

## Summary
Add tool argument completion support via a `@Complete()` decorator or `completeArgument` option on `@Tool()`. When an MCP client requests completions for a tool parameter, the framework invokes the registered completion handler and returns matching values. This enables IDE-like autocomplete for tool parameters.

## Background / Context
The MCP protocol supports argument completions — clients can request completion suggestions for tool parameters as users type. This is exposed in the SDK via `server.complete()`. FastMCP (Python) supports this via `@complete("param_name")` decorators. Our framework should provide equivalent functionality with a NestJS-idiomatic API.

Two API styles are proposed in the design artifact:
1. `@Complete('paramName', handler)` decorator on a `@Tool` method
2. `completeArgument` option in `@Tool()` decorator options

Both should be supported for flexibility.

## Acceptance Criteria
- [ ] `@Complete('paramName')` decorator can be applied to a method in the same class as a `@Tool()` method, linking the completion handler to that tool's parameter
- [ ] Alternative: `@Tool({ completeArgument: { paramName: handlerFn } })` inline option
- [ ] Completion handler signature: `(value: string, context?: McpCompletionContext) => Promise<string[]>` or `string[]`
- [ ] `McpCompletionContext` includes: `identity` (McpIdentity), `argument` (param name), `currentValue` (partial input)
- [ ] Framework registers completion handlers with the SDK's `server.complete()` mechanism
- [ ] Partial input filtering is handled by the completion handler (framework does not auto-filter)
- [ ] Completions work for tools registered via both `McpModule.forRoot()` and `McpModule.forFeature()`
- [ ] If no completion handler is registered for a parameter, the client receives an empty completions response
- [ ] Resource template parameter completions are supported: `@Complete('paramName')` can be applied to a method in the same class as a `@Resource()` template method, linking completions to that template's parameter
- [ ] Completion requests from the client include `{ argument: { name, value } }`. The framework routes by `name` to find the registered completion handler. The `value` is the partial input passed to the handler

## BDD Scenarios

```gherkin
Feature: Argument Completions
  Tool and resource parameters can have completion handlers that return
  suggestions as the user types, enabling IDE-like autocomplete in MCP clients.

  Rule: Completion handlers return suggestions for partial input

    Scenario: Completion handler filters by prefix
      Given a tool "search_emails" with completions for the "folder" parameter returning "Inbox", "Sent", "Drafts", and "Archive"
      When a client requests completions for "folder" with partial value "In"
      Then the response contains "Inbox"

    Scenario: Inline completion handler on a tool
      Given a tool "move_email" with an inline completion handler for the "folder" parameter
      When a client requests completions for "folder" with partial value "D"
      Then the response contains "Drafts"

    Scenario: Multiple matches returned for a partial value
      Given a tool "search_emails" with completions for the "folder" parameter returning "Sent Items", "Sent Archive", and "Spam"
      When a client requests completions for "folder" with partial value "Sen"
      Then the response contains "Sent Items" and "Sent Archive"

    Scenario: No matches returns an empty completion list
      Given a tool "search_emails" with completions for the "folder" parameter
      When a client requests completions for "folder" with partial value "Xyz"
      Then the response contains an empty list

  Rule: Missing completion handlers return empty results

    Scenario: Parameter without a completion handler returns no suggestions
      Given a tool "add_numbers" with no completion handlers registered
      When a client requests completions for the "a" parameter
      Then the response contains an empty list

  Rule: Completion handlers receive caller context

    Scenario: Completion handler filters results based on caller identity
      Given a tool with a completion handler that restricts results by the caller's permissions
      When an authenticated user with limited access requests completions
      Then the handler receives the caller's identity
      And only returns values the caller is permitted to see

  Rule: Paginated completion results

    Scenario: Large result set includes pagination metadata
      Given a completion handler that matches 100 values but limits the response to 10
      When a client requests completions
      Then the response contains 10 values with an indication that more results are available and a total count of 100

  Rule: Resource template parameter completions

    Scenario: Completions work for resource template parameters
      Given a resource with URI template "users://{user_id}/profile" and completions for "user_id"
      When a client requests completions for "user_id" with partial value "usr-"
      Then the completion handler returns matching user IDs
```

## FastMCP Parity
FastMCP (Python) supports argument completions via `@complete("param_name")` decorators on tool functions, and also supports completions for resource template parameters. Our `@Complete('paramName')` decorator mirrors FastMCP's `@complete` API. FastMCP also supports `completeArgument` callbacks inline — we provide both decorator and inline options for flexibility.

## Dependencies
- **Depends on:** CORE-001 (@Tool decorator) — tool registration must scan for `@Complete` metadata
- **Depends on:** CORE-005 (Handler registry) — completion handlers registered alongside tools in the registry
- **Blocks:** none

## Technical Notes
- SDK API: The SDK's `McpServer` supports completions via the `complete` capability. When a `CompleteRequest` is received, the server looks up the registered completion handler for the reference type (tool argument) and invokes it.
- `@Complete()` decorator stores metadata via `Reflect.defineMetadata`:
  ```typescript
  export function Complete(paramName: string): MethodDecorator {
    return (target, propertyKey, descriptor) => {
      const existing = Reflect.getMetadata('mcp:completions', target.constructor) || {};
      // Key: toolMethodName.paramName -> completionMethodName
      // We need to link this to the correct tool — use the method name
      existing[paramName] = propertyKey;
      Reflect.defineMetadata('mcp:completions', existing, target.constructor);
    };
  }
  ```
- During tool registration scanning, the framework checks for `mcp:completions` metadata on the class and wires up the completion handlers
- The `completeArgument` inline option is simpler but doesn't support DI in the handler. The `@Complete` decorator method approach allows the handler to be a class method with full DI access.
- SDK completion response format: `{ completion: { values: string[], hasMore?: boolean, total?: number } }`
