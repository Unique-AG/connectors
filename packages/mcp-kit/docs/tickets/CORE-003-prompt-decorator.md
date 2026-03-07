# CORE-003: @Prompt() decorator

## Summary
Implement the `@Prompt()` method decorator that marks NestJS service methods as MCP prompts. The decorator auto-derives the prompt name from the method name (camelCase to kebab-case) and accepts a Zod schema for parameter validation.

## Background / Context
The `@Prompt()` decorator marks NestJS service methods as MCP prompts with automatic kebab-case name derivation and symbol-based metadata keys consistent with `@Tool()` and `@Resource()`.

MCP prompts are templates that return `GetPromptResult` (a list of messages). Parameters are validated with Zod before the handler is called, same as tools.

## Acceptance Criteria
- [ ] `@Prompt()` is exported from `@unique-ag/nestjs-mcp`
- [ ] Name auto-derived from method name using camelCase-to-kebab-case conversion
- [ ] Name can be overridden via `name` option
- [ ] `description` is required in options
- [ ] `parameters` accepts optional `z.ZodObject` for input validation
- [ ] `parameters` accepts `Record<string, z.ZodType>` shorthand (same as @Tool) — the shorthand is wrapped into `z.object(record)` during metadata resolution, so `PromptMetadata.parameters` is always a `z.ZodObject` or `undefined`
- [ ] `title` option stores a human-readable display name, separate from the identifier `name`
- [ ] `title` appears in `listPrompts` response as the `title` field
- [ ] `icons` option stores array of `McpIcon` objects and includes them in `listPrompts` responses (v2.13.0+ parity)
- [ ] `meta` option stores custom metadata and emits it as `_meta` in list responses (v2.11.0+ parity)
- [ ] `version` option stores a string or number version identifier in metadata (v3.0.0+ parity)
- [ ] Metadata stored under `MCP_PROMPT_METADATA` symbol
- [ ] `PromptOptions` and `PromptMetadata` TypeScript interfaces exported

## BDD Scenarios

```gherkin
Feature: @Prompt() decorator for MCP prompt registration

  Rule: Prompt name is derived from the method name or explicitly set

    Scenario: Name auto-derived from method name using kebab-case
      Given a service method named "composeOutreach" decorated as a prompt with description "Draft email"
      When an MCP client lists available prompts
      Then a prompt named "compose-outreach" appears in the list

    Scenario: Explicit name overrides auto-derived name
      Given a prompt with explicit name "draft-email"
      When an MCP client lists available prompts
      Then a prompt named "draft-email" appears in the list

  Rule: Prompt parameters are validated before the handler runs

    Scenario: Valid parameters are accepted
      Given a prompt "draft-email" that requires a "recipient" parameter as a valid email
      When an MCP client calls the prompt with recipient "user@example.com"
      Then the prompt executes successfully

    Scenario: Invalid parameters are rejected
      Given a prompt "draft-email" that requires a "recipient" parameter as a valid email
      When an MCP client calls the prompt with recipient "not-an-email"
      Then the call is rejected with a parameter validation error

    Scenario: Prompt with no parameters accepts empty arguments
      Given a prompt "daily-summary" with no declared parameters
      When an MCP client calls the prompt with no arguments
      Then the prompt executes successfully

  Rule: Title is a display name independent from the identifier

    Scenario: Title appears in prompt listing alongside the name
      Given a prompt on method "composeOutreach" with title "Compose Outreach Email"
      When an MCP client lists available prompts
      Then the prompt name is "compose-outreach"
      And the prompt title is "Compose Outreach Email"

  Rule: Description is mandatory

    Scenario: Omitting description causes a compile-time error
      Given a developer decorates a method as a prompt without providing a description
      When the project is compiled
      Then a type error is raised for the missing "description" property

  Rule: Icons, meta, and version appear in prompt listings

    Scenario: Prompt icons are included in the prompts list
      Given a prompt with an icon at "https://example.com/email.svg"
      When an MCP client lists available prompts
      Then the prompt entry includes that icon URI

    Scenario: Prompt meta is included as metadata in the prompts list
      Given a prompt with meta containing key "category" set to "communication"
      When an MCP client lists available prompts
      Then the prompt entry includes metadata with category "communication"
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Blocks: CORE-005, CORE-015

## Interface Contract
Consumed by CORE-005 (registry), CORE-013 (handlers):
```typescript
export const MCP_PROMPT_METADATA = Symbol('MCP_PROMPT_METADATA');

export interface PromptOptions {
  name?: string;
  title?: string;                          // human-readable display name (separate from identifier `name`)
  description: string;
  parameters?: z.ZodObject<any> | Record<string, z.ZodType>;
  icons?: McpIcon[];                       // visual representations for client display (v2.13.0+ parity)
  meta?: Record<string, unknown>;          // custom metadata passed to clients in _meta field (v2.11.0+ parity)
  version?: string | number;               // version identifier; highest version wins on duplicate name (v3.0.0+ parity)
}

export interface PromptMetadata {
  name: string;                          // resolved (auto-derived or explicit)
  title?: string;                        // human-readable display name
  description: string;
  parameters?: z.ZodObject<any>;         // resolved to ZodObject if shorthand
  icons?: McpIcon[];                     // visual representations for client display
  meta?: Record<string, unknown>;        // custom metadata emitted as _meta
  version?: string | number;             // version identifier for multi-version support
  methodName: string;
}
```

## Technical Notes
- Name derivation helper: `camelToKebabCase(name: string): string` — `composeOutreach` -> `compose-outreach`
- Same shorthand detection logic as @Tool for the `parameters` field
- Metadata storage: `Reflect.defineMetadata(MCP_PROMPT_METADATA, resolvedMetadata, descriptor.value)`
- File location: `packages/nestjs-mcp/src/decorators/prompt.decorator.ts`
- The MCP protocol prompt parameters are sent as `{ name, description, required }` tuples, not JSON Schema. The registry/handler must convert `z.ZodObject` keys to this format when responding to `prompts/list`. Note: all MCP prompt arguments are strings at the protocol level — the Zod schema validates the string values but the wire format is always `Record<string, string>`.
- **Return type handling**: Handlers may return a plain `string`, `McpMessage[]`, or a `PromptResult` object (see Technical Notes below). The framework normalizes all return types to `GetPromptResult` before sending to the client.
- **PromptResult return type**: Prompt handler methods may return a `PromptResult` object for richer responses:
  ```typescript
  interface PromptResult {
    messages: string | McpMessage[];
    description?: string; // runtime override of prompt description
    meta?: Record<string, unknown>; // included in response _meta
  }
  ```
  When the handler returns a plain string or `McpMessage[]`, it is auto-wrapped into `PromptResult`. When it returns a `PromptResult` object, `description` and `meta` are included in the `GetPromptResult` response.
