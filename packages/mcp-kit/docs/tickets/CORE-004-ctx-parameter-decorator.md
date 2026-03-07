# CORE-004: @Ctx() parameter decorator

## Summary
Implement the `@Ctx()` parameter decorator that marks a method parameter as the injection point for `McpContext`. The framework reads the stored parameter index at invocation time and injects the `McpContext` instance at that position, allowing it to be placed at any parameter position.

## Background / Context
The `@Ctx()` decorator decouples parameter position from context injection: the framework reads the metadata-stored index and places `McpContext` at that position, allowing tools to declare `@Ctx()` at any parameter slot.

This follows the same pattern as NestJS's `@Body()`, `@Param()`, etc., which use `Reflect.defineMetadata` to store parameter indices.

## Acceptance Criteria
- [ ] `@Ctx()` is exported from `@unique-ag/nestjs-mcp`
- [ ] Uses `Reflect.defineMetadata` with `MCP_CTX_METADATA` symbol key
- [ ] Stores the parameter index on the method's prototype+key
- [ ] Works at any parameter position (0, 1, 2, etc.)
- [ ] When `@Ctx()` is not used, the framework falls back to positional injection (input at 0, context at 1) for backwards compatibility during migration
- [ ] `MCP_CTX_METADATA` symbol is exported (for framework internals and testing)

## BDD Scenarios

```gherkin
Feature: @Ctx() parameter decorator for McpContext injection

  Rule: McpContext is injected at the decorated parameter position

    Scenario Outline: Context injected at any parameter position
      Given a tool method where @Ctx() is applied at parameter position <position>
      When an MCP client calls the tool
      Then the parameter at position <position> receives the McpContext instance
      And all other parameters receive their expected values

      Examples:
        | position |
        | 0        |
        | 1        |
        | 2        |

  Rule: Omitting @Ctx() means no context is injected

    Scenario: Tool method without @Ctx() receives only the validated input
      Given a tool method "search" with a single input parameter and no @Ctx() decorator
      When an MCP client calls "search" with query "test"
      Then the method receives the validated input as its only argument
      And no McpContext is passed to the method

  Rule: Multiple @Ctx() decorators on the same method are not supported

    Scenario: Only the last @Ctx() position is used when multiple are applied
      Given a tool method with @Ctx() applied at both position 0 and position 2
      When an MCP client calls the tool
      Then McpContext is injected at position 2 only
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Blocks: CORE-005 — registry reads @Ctx() metadata for each discovered method

## Technical Notes
- Implementation (from design artifact):
  ```typescript
  export const MCP_CTX_METADATA = Symbol('MCP_CTX');

  export function Ctx(): ParameterDecorator {
    return (target, propertyKey, parameterIndex) => {
      Reflect.defineMetadata(MCP_CTX_METADATA, parameterIndex, target, propertyKey!);
    };
  }
  ```
- At invocation time, the handler reads:
  ```typescript
  const ctxParamIndex = Reflect.getMetadata(MCP_CTX_METADATA, toolInstance, methodName);
  const args: unknown[] = [input];
  if (ctxParamIndex !== undefined) {
    while (args.length <= ctxParamIndex) args.push(undefined);
    args[ctxParamIndex] = mcpContext;
  }
  ```
- File location: `packages/nestjs-mcp/src/decorators/ctx.decorator.ts`
- Note: `target` in the ParameterDecorator is the prototype (for instance methods), so metadata is on the prototype+propertyKey pair
