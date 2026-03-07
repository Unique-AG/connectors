# CORE-023: Static resource classes

## Summary
Provide pre-built resource classes (`McpTextResource`, `McpBinaryResource`, `McpFileResource`, `McpHttpResource`, `McpDirectoryResource`) that can be registered programmatically via `McpModule.forRoot({ staticResources: [...] })` or via `McpRegistryService.addResource()`. These are NestJS equivalents of FastMCP's built-in `TextResource`, `BinaryResource`, `FileResource`, `HttpResource`, and `DirectoryResource`.

## Background / Context
FastMCP provides pre-built resource objects registered programmatically via `mcp.add_resource()`:
- **TextResource** — static string content, returned as-is on every read
- **BinaryResource** — static bytes, returned as base64 blob
- **FileResource** — lazy-reads a local file on each access
- **HttpResource** — fetches an HTTP URL on each access (requires httpx in Python; axios/node-fetch in Node)
- **DirectoryResource** — lists directory contents as JSON

In NestJS, these are provided as classes implementing a common `McpStaticResource` interface. They can be registered without writing decorated handler classes — useful for simple, configuration-driven resources.

## Acceptance Criteria
- [ ] `McpStaticResource` interface with: `uri: string`, `name?: string`, `description?: string`, `mimeType?: string`, `tags?: string[]`, `read(): Promise<string | Buffer>`
- [ ] `McpTextResource` class: accepts `{ uri, content: string, name?, description?, mimeType?, tags? }`, `read()` returns the static string
- [ ] `McpBinaryResource` class: accepts `{ uri, data: Buffer, name?, description?, mimeType?, tags? }`, `read()` returns the Buffer
- [ ] `McpFileResource` class: accepts `{ uri, path: string, name?, description?, mimeType?, tags? }`, `read()` reads the file lazily on each call
- [ ] `McpFileResource` throws `ResourceError` if the file does not exist at read time
- [ ] `McpHttpResource` class: accepts `{ uri, url: string, name?, description?, mimeType?, tags?, headers?: Record<string, string> }`, `read()` fetches the URL on each call
- [ ] `McpHttpResource` throws `ResourceError` on HTTP errors (non-2xx status)
- [ ] `McpDirectoryResource` class: accepts `{ uri, path: string, name?, description?, mimeType?, tags? }`, `read()` returns JSON array of directory entries
- [ ] Directory entries have shape: `{ name: string, path: string, isDirectory: boolean, size?: number, mtime?: string }`
- [ ] All static resource classes can be registered via `McpModule.forRoot({ staticResources: [...] })`
- [ ] All static resource classes can be registered at runtime via `McpRegistryService.addResource(resource)`
- [ ] All registered static resources appear in `listResources` responses with correct `uri`, `name`, `description`, and `mimeType`
- [ ] All static resource classes exported from `@unique-ag/nestjs-mcp`
- [ ] Aliased exports for FastMCP naming: `TextResource`, `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource`
- [ ] When a `FileResource` or `HttpResource` read fails (file not found, HTTP error, permission denied), the handler throws `ResourceError` with an appropriate message. It does NOT return an empty response or silently swallow the error. The error is caught by `McpExceptionFilter` and returned as an MCP error response

## BDD Scenarios

```gherkin
Feature: Static resource classes
  Pre-built resource classes allow developers to expose static content,
  files, HTTP endpoints, and directories as MCP resources without
  writing custom handler classes.

  Rule: Text resources serve static string content

    Scenario: A text resource returns its configured content
      Given a text resource "data://greeting" is registered with content "Hello!" and name "Greeting"
      When a client calls listResources
      Then the list includes a resource with URI "data://greeting" and name "Greeting"
      When a client reads the resource "data://greeting"
      Then the response contains the text "Hello!"

  Rule: Binary resources serve raw data as base64

    Scenario: A binary resource returns base64-encoded content
      Given a binary resource "data://logo" is registered with PNG image data and mime type "image/png"
      When a client reads the resource "data://logo"
      Then the response contains base64-encoded blob content
      And the mime type is "image/png"

  Rule: File resources read from disk lazily on each access

    Scenario: A file resource reflects the current file contents
      Given a file resource "file://config" is registered pointing to "/etc/app/config.json"
      And the file contains '{"key": "value1"}'
      When a client reads the resource "file://config"
      Then the response contains '{"key": "value1"}'
      When the file is updated to contain '{"key": "value2"}'
      And a client reads the resource "file://config" again
      Then the response contains '{"key": "value2"}'

    Scenario: A file resource for a missing file returns an error
      Given a file resource "file://missing" is registered pointing to "/nonexistent/file.txt"
      When a client reads the resource "file://missing"
      Then the server returns a resource error indicating the file was not found

  Rule: HTTP resources fetch from a URL on each access

    Scenario: An HTTP resource returns the fetched content
      Given an HTTP resource "remote://status" is registered pointing to "https://api.example.com/status"
      And that URL responds with '{"status": "ok"}'
      When a client reads the resource "remote://status"
      Then the response contains '{"status": "ok"}'

    Scenario: An HTTP resource returns an error for failed requests
      Given an HTTP resource "remote://broken" is registered pointing to "https://api.example.com/broken"
      And that URL responds with HTTP 500
      When a client reads the resource "remote://broken"
      Then the server returns a resource error indicating an HTTP failure

  Rule: Directory resources list filesystem entries as JSON

    Scenario: A directory resource returns its contents as a structured listing
      Given a directory resource "dir://src" is registered pointing to "./src"
      And the directory contains files "index.ts", "utils.ts" and subdirectory "lib"
      When a client reads the resource "dir://src"
      Then the response contains a JSON array with entries for each item
      And each file entry includes its name, path, size, and modification time
      And the subdirectory entry "lib" is marked as a directory

  Rule: All static resources appear in resource discovery

    Scenario: Multiple static resource types are all discoverable
      Given a text resource, a file resource, an HTTP resource, and a directory resource are registered
      When a client calls listResources
      Then all four resources appear with their respective URI, name, description, and mime type

  Rule: Static resources can be registered at runtime

    Scenario: A static resource added at runtime becomes immediately available
      Given the server started with no static resources
      When a server-side service registers a text resource "data://dynamic" with content "added at runtime"
      Then a client calling listResources sees the resource "data://dynamic"
      And reading "data://dynamic" returns "added at runtime"
```

## Dependencies
- Depends on: CORE-002 — resource decorator and metadata interface
- Depends on: CORE-005 — handler registry for registration and lookup
- Depends on: CORE-013 — MCP handlers for read dispatch
- Blocks: none

## Technical Notes
- `McpStaticResource` interface:
  ```typescript
  export interface McpStaticResource {
    uri: string;
    name?: string;
    description?: string;
    mimeType?: string;
    tags?: string[];
    read(): Promise<string | Buffer>;
  }
  ```
- Registration in module config:
  ```typescript
  McpModule.forRoot({
    staticResources: [
      new McpTextResource({ uri: 'data://greeting', content: 'Hello!', name: 'Greeting' }),
      new McpFileResource({ uri: 'file://config', path: '/etc/config.json', mimeType: 'application/json' }),
      new McpHttpResource({ uri: 'remote://status', url: 'https://api.example.com/status' }),
      new McpDirectoryResource({ uri: 'dir://src', path: './src' }),
    ]
  })
  ```
- `McpFileResource` uses `fs.promises.readFile()` — lazy on each call, never caches
- `McpHttpResource` uses `axios` (already a common NestJS dependency via `@nestjs/axios`) or falls back to Node's native `fetch`. Does not cache — each `read()` fetches fresh
- `McpDirectoryResource` uses `fs.promises.readdir()` with `withFileTypes: true` and `fs.promises.stat()` for size/mtime
- `ResourceError` (from CORE-008) is thrown for file-not-found and HTTP errors
- Aliased exports for FastMCP compatibility:
  ```typescript
  export { McpTextResource as TextResource };
  export { McpBinaryResource as BinaryResource };
  export { McpFileResource as FileResource };
  export { McpHttpResource as HttpResource };
  export { McpDirectoryResource as DirectoryResource };
  ```
- `McpRegistryService.addResource()` accepts a `McpStaticResource` instance and registers it in the handler registry at runtime. This triggers a `sendResourceListChanged()` notification if resource subscriptions are active.
- **FastMCP parity:** Maps directly to FastMCP's `TextResource`, `BinaryResource`, `FileResource`, `HttpResource`, `DirectoryResource` built-in classes.
- File locations:
  - `packages/nestjs-mcp/src/resources/mcp-static-resource.interface.ts`
  - `packages/nestjs-mcp/src/resources/mcp-text-resource.ts`
  - `packages/nestjs-mcp/src/resources/mcp-binary-resource.ts`
  - `packages/nestjs-mcp/src/resources/mcp-file-resource.ts`
  - `packages/nestjs-mcp/src/resources/mcp-http-resource.ts`
  - `packages/nestjs-mcp/src/resources/mcp-directory-resource.ts`
  - `packages/nestjs-mcp/src/resources/index.ts`
