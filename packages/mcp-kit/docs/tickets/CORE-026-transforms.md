# CORE-026: McpTransform — Server-wide Component Transforms

## Summary
Implement `McpTransform` interface and `McpModule.forRoot({ transforms: McpTransform[] })` to support server-wide modifiers that change how components (tools, resources, prompts) are presented to clients. Transforms operate at serve-time (list/call time) and can rename components, modify descriptions, override annotations, reorder parameters, and filter parameter descriptions. They apply to ALL components regardless of which module registered them.

## Background / Context
FastMCP v3.1.0+ supports `transforms=[Transform(...)]` on the FastMCP constructor. These are server-wide modifiers that change how components are presented to clients at serve-time. Unlike per-component decorators, transforms apply globally to all registered components.

In NestJS, this maps to a `McpTransform` interface and configuration via `McpModule.forRoot({ transforms })`. Transforms are applied in order, after per-component prefix (CORE-016) but before final response serialization.

## Acceptance Criteria
- [ ] `McpTransform` interface exported from `@unique-ag/nestjs-mcp`
- [ ] `McpModule.forRoot({ transforms: McpTransform[] })` accepts an ordered array of transforms
- [ ] Each transform can optionally define `transformTool`, `transformResource`, `transformPrompt` methods
- [ ] Transforms are applied at `listTools`/`callTool` time for tools
- [ ] Transforms are applied at `listResources`/`readResource` time for resources
- [ ] Transforms are applied at `listPrompts`/`getPrompt` time for prompts
- [ ] Transforms are applied in array order (first transform runs first)
- [ ] Transforms are applied after CORE-016 prefix but before final response serialization
- [ ] `callTool` resolves the transformed name back to the original handler correctly
- [ ] Built-in `McpPrefixTransform` adds a prefix to all component names (global override of CORE-016 prefix)
- [ ] Built-in `McpDescriptionTransform` appends or prepends text to all component descriptions
- [ ] Built-in `McpAnnotationTransform` overrides annotation fields on all tools

## BDD Scenarios

```gherkin
Feature: Server-wide component transforms
  Transforms modify how tools, resources, and prompts are presented to
  MCP clients without changing the underlying handler implementations.

  Rule: Prefix transform renames all components

    Scenario: All tool names are prefixed when a prefix transform is configured
      Given an MCP server with a prefix transform set to "v2"
      And a tool "search" is registered
      When a client calls listTools
      Then the tool appears with name "v2_search"

    Scenario: Resources and prompts are also prefixed
      Given an MCP server with a prefix transform set to "v2"
      And a resource named "config" and a prompt named "summarize" are registered
      When a client calls listResources
      Then the resource appears with name "v2_config"
      When a client calls listPrompts
      Then the prompt appears with name "v2_summarize"

  Rule: Description transform modifies component descriptions

    Scenario: Text is appended to all tool descriptions
      Given an MCP server with a description transform appending " [BETA]"
      And a tool "search" is registered with description "Search documents"
      When a client calls listTools
      Then the tool description is "Search documents [BETA]"

    Scenario: Text is prepended to all tool descriptions
      Given an MCP server with a description transform prepending "EXPERIMENTAL: "
      And a tool "search" is registered with description "Search documents"
      When a client calls listTools
      Then the tool description is "EXPERIMENTAL: Search documents"

  Rule: Multiple transforms are applied in order

    Scenario: Prefix transform runs before description transform
      Given an MCP server with transforms: prefix "v2" then append " [BETA]"
      And a tool "search" is registered with description "Search documents"
      When a client calls listTools
      Then the tool appears with name "v2_search" and description "Search documents [BETA]"

  Rule: Tool calls use the transformed name and resolve to the original handler

    Scenario: A client calls a tool by its transformed name
      Given an MCP server with a prefix transform set to "v2"
      And a tool "search" is registered
      When a client calls the tool "v2_search" with { "query": "test" }
      Then the original "search" handler executes with { "query": "test" }
      And the client receives the result

    Scenario: Calling the original untransformed name fails
      Given an MCP server with a prefix transform set to "v2"
      And a tool "search" is registered
      When a client calls the tool "search" with { "query": "test" }
      Then the server returns a "tool not found" error

  Rule: Annotation transform overrides tool annotations

    Scenario: All tools receive overridden annotation values
      Given an MCP server with an annotation transform setting "readOnlyHint" to true
      And a tool "delete_record" is registered without annotation hints
      When a client calls listTools
      Then the "delete_record" tool has annotation "readOnlyHint" set to true
```

## FastMCP Parity
Maps to FastMCP v3.1.0+ `transforms=` parameter on the FastMCP constructor. FastMCP's transform system modifies component presentation at serve-time. Built-in transforms include prefix, description modification, and annotation overrides.

## Dependencies
- **Depends on:** CORE-012 — McpModule configuration (transforms added to McpOptions)
- **Depends on:** CORE-013 — handlers apply transforms at list/call time
- **Blocks:** none

## Technical Notes
- `McpTransform` interface:
  ```typescript
  interface ToolInfo {
    name: string;
    description?: string;
    inputSchema: Record<string, unknown>;
    annotations?: Record<string, unknown>;
  }

  interface ResourceInfo {
    uri: string;
    name: string;
    description?: string;
    mimeType?: string;
  }

  interface PromptInfo {
    name: string;
    description?: string;
    arguments?: Array<{ name: string; description?: string; required?: boolean }>;
  }

  interface McpTransform {
    // Applied to tools at listTools/callTool time
    transformTool?: (tool: ToolInfo) => ToolInfo;
    // Applied to resources at listResources/readResource time
    transformResource?: (resource: ResourceInfo) => ResourceInfo;
    // Applied to prompts at listPrompts/getPrompt time
    transformPrompt?: (prompt: PromptInfo) => PromptInfo;
  }
  ```
- Built-in transforms:
  ```typescript
  // Adds prefix to all component names (global override of CORE-016 prefix)
  McpPrefixTransform({ prefix: string }): McpTransform;

  // Appends or prepends text to all component descriptions
  McpDescriptionTransform({ append?: string; prepend?: string }): McpTransform;

  // Overrides annotation fields on all tools
  McpAnnotationTransform(annotations: Partial<ToolAnnotations>): McpTransform;
  ```
- Transforms are stored in `McpOptions.transforms` and injected into handlers via `MCP_OPTIONS`
- For `callTool`, the handler must maintain a reverse mapping from transformed name back to original name. This mapping is rebuilt whenever the transform chain or tool list changes.
- Transforms are pure functions — they receive a component info object and return a (potentially modified) copy. They must not mutate the input.
- File location: `packages/nestjs-mcp/src/transforms/`
  - `packages/nestjs-mcp/src/transforms/mcp-transform.interface.ts`
  - `packages/nestjs-mcp/src/transforms/prefix.transform.ts`
  - `packages/nestjs-mcp/src/transforms/description.transform.ts`
  - `packages/nestjs-mcp/src/transforms/annotation.transform.ts`
