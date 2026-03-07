# CORE-005: MCP handler registry

## Summary
Implement the `McpHandlerRegistry` service that discovers all `@Tool`, `@Resource`, and `@Prompt` decorated methods at application bootstrap using NestJS `DiscoveryService`. The registry stores metadata including method references, class references, `@Ctx()` parameter indices, and schema references, and supports multiple tool classes across multiple NestJS modules.

## Background / Context
The `McpHandlerRegistry` uses NestJS `DiscoveryService` and `MetadataScanner` to discover all decorated handler methods at bootstrap:
1. Uses symbol-based metadata keys (from CORE-001/002/003)
2. Reads `@Ctx()` parameter index metadata (from CORE-004)
3. Stores references needed by the pipeline runner (CORE-010) — class constructor ref, method ref
4. Validates for name collisions at boot time (throws on duplicate tool/resource/prompt names)
5. Uses the unified `@Resource()` with `kind` discriminator for both static resources and templates

## Acceptance Criteria
- [ ] `McpHandlerRegistry` is an `@Injectable()` singleton service
- [ ] Implements `OnApplicationBootstrap` to trigger discovery
- [ ] Uses NestJS `DiscoveryService` and `MetadataScanner` to find decorated methods
- [ ] Discovers `@Tool`, `@Resource`, `@Prompt` decorated methods across all providers and controllers
- [ ] Stores per-entry: `{ type, name, metadata, classRef, instance, methodName, ctxParamIndex, schemas }`
- [ ] Supports multiple McpTool classes registered in different NestJS modules
- [ ] Throws descriptive error at boot time if two tools share the same name
- [ ] Throws descriptive error at boot time if two resources share the same URI
- [ ] Throws descriptive error at boot time if two prompts share the same name
- [ ] Provides lookup methods: `getTools()`, `findTool(name)`, `getResources()`, `findResourceByUri(uri)`, `getPrompts()`, `findPrompt(name)`
- [ ] For template resources, `findResourceByUri(uri)` uses `path-to-regexp` to match and extract params
- [ ] Exported from `@unique-ag/nestjs-mcp`

## BDD Scenarios

```gherkin
Feature: MCP handler registry discovers and indexes decorated methods

  Rule: All decorated methods are discovered across modules at bootstrap

    Scenario: Handlers from multiple modules are registered
      Given module A contains 2 tool methods and 1 resource method
      And module B contains 1 tool method and 1 prompt method
      When the application starts
      Then the server reports 3 available tools
      And the server reports 1 available resource
      And the server reports 1 available prompt

  Rule: Duplicate names are rejected at boot time

    Scenario: Two tools with the same name cause a startup error
      Given module A registers a tool named "search"
      And module B registers a tool named "search"
      When the application starts
      Then the application fails to start
      And the error message mentions "search" and both service class names

    Scenario: Two resources with the same URI cause a startup error
      Given module A registers a resource with URI "config://app/settings"
      And module B registers a resource with URI "config://app/settings"
      When the application starts
      Then the application fails to start
      And the error message mentions "config://app/settings"

    Scenario: Two prompts with the same name cause a startup error
      Given module A registers a prompt named "draft-email"
      And module B registers a prompt named "draft-email"
      When the application starts
      Then the application fails to start
      And the error message mentions "draft-email"

  Rule: Resources are matched by URI, including template parameters

    Scenario: Static resource is found by exact URI match
      Given a registered resource with URI "config://app/settings"
      When an MCP client reads "config://app/settings"
      Then the resource handler is invoked

    Scenario: Template resource extracts parameters from the URI
      Given a registered resource template with URI "users://{user_id}/profile"
      When an MCP client reads "users://abc-123/profile"
      Then the resource handler is invoked with user_id "abc-123"

    Scenario: Unregistered URI returns not found
      Given no resource is registered for URI "unknown://missing"
      When an MCP client reads "unknown://missing"
      Then the client receives a resource-not-found error

  Rule: @Ctx() parameter position is recorded for each handler

    Scenario: Handler with @Ctx() receives context at the decorated position
      Given a tool method where @Ctx() is on the second parameter
      When an MCP client calls the tool
      Then the first parameter receives the validated input
      And the second parameter receives the McpContext

    Scenario: Handler without @Ctx() does not receive context
      Given a tool method with no @Ctx() decorator
      When an MCP client calls the tool
      Then the method receives only the validated input
```

## Dependencies
- Depends on: INFRA-001 — package must exist
- Depends on: CORE-001 — `MCP_TOOL_METADATA` symbol and `ToolMetadata` interface
- Depends on: CORE-002 — `MCP_RESOURCE_METADATA` symbol and `ResourceMetadata` interface
- Depends on: CORE-003 — `MCP_PROMPT_METADATA` symbol and `PromptMetadata` interface
- Depends on: CORE-004 — `MCP_CTX_METADATA` symbol for parameter index
- Blocks: CORE-006, CORE-009, CORE-014, CORE-015, CORE-016

## Interface Contract
Consumed by CORE-010 (pipeline runner), CORE-013 (handlers), CORE-014 (completions), CORE-015 (filtering), CORE-016 (composition):
```typescript
export interface RegistryEntry {
  type: 'tool' | 'resource' | 'prompt';
  name: string;
  metadata: ToolMetadata | ResourceMetadata | PromptMetadata;
  classRef: Type;
  instance: object;
  methodName: string;
  ctxParamIndex: number | undefined;
}

@Injectable()
export class McpHandlerRegistry implements OnApplicationBootstrap {
  getTools(): RegistryEntry[];
  findTool(name: string): RegistryEntry | undefined;
  getResources(): RegistryEntry[];                              // all (static + template)
  getStaticResources(): RegistryEntry[];                        // kind === 'static' only
  getTemplateResources(): RegistryEntry[];                      // kind === 'template' only
  findResourceByUri(uri: string): { entry: RegistryEntry; params: Record<string, string> } | undefined;
  getPrompts(): RegistryEntry[];
  findPrompt(name: string): RegistryEntry | undefined;
  getAll(): RegistryEntry[];                                    // debugging/introspection
}
```

## Technical Notes
- Discovery uses `Reflect.getMetadata(MCP_TOOL_METADATA, instance, methodName)` (symbol keys on prototype+key)
- For `@Ctx()` index: `Reflect.getMetadata(MCP_CTX_METADATA, instance, methodName)`
- `path-to-regexp` is a core dependency (INFRA-001) for matching template resource URIs
- Module-scoped discovery via `discoveredToolsByMcpModuleId` map for multi-module support
- File location: `packages/nestjs-mcp/src/services/mcp-handler-registry.service.ts`
