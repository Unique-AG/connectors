# SDK-002: ctx.sample() -- LLM sampling

## Summary
Expose the MCP SDK's `server.createMessage()` method through `McpContext.sample(prompt, options?)`, enabling tools to request LLM completions from the connected MCP client. This allows tools to perform server-initiated reasoning, summarization, or classification without needing their own LLM integration.

## Background / Context
The MCP SDK v1.25.2 supports server-initiated sampling — the server sends a `CreateMessageRequest` to the client, which performs an LLM completion and returns the result. This is a powerful capability for building intelligent tools that leverage the client's LLM without requiring separate API keys or model integrations on the server side.

Sampling is only meaningful in stateful sessions where the client maintains a bidirectional connection (Streamable HTTP with sessions, SSE). STDIO transport also supports it. Stateless HTTP requests cannot support sampling because there is no way to send requests back to the client.

## Acceptance Criteria
- [ ] `McpContext.sample(prompt: string, options?: SamplingOptions): Promise<string>` is available via `@Ctx()`
- [ ] `SamplingOptions` includes: `maxTokens`, `temperature`, `model`, `systemPrompt`, `stopSequences`, `includeContext` (maps to SDK `CreateMessageRequest`)
- [ ] Returns the text content of the LLM response (first text content block)
- [ ] Default `maxTokens` is configurable at module level (`McpModule.forRoot({ sampling: { defaultMaxTokens: 1024 } })`)
- [ ] Throws `McpSamplingUnsupportedError` if the client does not support sampling (capability check)
- [ ] Throws `McpSamplingError` if the LLM call fails
- [ ] Abort signal from the tool's request context is forwarded to the sampling call

## BDD Scenarios

```gherkin
Feature: LLM sampling via MCP client
  Tools can request LLM completions from the connected MCP client,
  enabling server-side reasoning without separate LLM integrations.

  Background:
    Given an MCP server with sampling enabled
    And a connected MCP client that supports sampling

  Rule: Successful sampling returns text content

    Scenario: Tool requests a summarization and receives text
      Given a tool "summarize_email" that requests an LLM summary of its input
      When an MCP client calls "summarize_email" with body: "Meeting at 3pm tomorrow"
      Then the tool receives a text response from the client's LLM
      And the tool returns the summary to the client

    Scenario: Tool provides a system prompt for classification
      Given a tool "classify_ticket" that uses a system prompt "You are a support ticket classifier"
      When an MCP client calls "classify_ticket" with text: "My login is broken"
      Then the LLM request includes the system prompt
      And the tool receives the classification result as text

  Rule: Module-level defaults apply when options are omitted

    Scenario: Default max tokens used when not specified per-call
      Given the MCP module is configured with a default max tokens of 2048
      And a tool "summarize" that requests an LLM completion without specifying max tokens
      When an MCP client calls "summarize"
      Then the LLM request uses max tokens of 2048

  Rule: Sampling requires a capable, stateful client

    Scenario: Client does not support sampling
      Given a connected MCP client that does not support sampling
      And a tool "ai_tool" that requests an LLM completion
      When an MCP client calls "ai_tool"
      Then the tool receives an error indicating the client does not support sampling

    Scenario: Sampling attempted on a stateless connection
      Given a stateless Streamable HTTP connection with no session
      And a tool "ai_tool" that requests an LLM completion
      When an MCP client calls "ai_tool"
      Then the tool receives an error indicating sampling requires a stateful session

  Rule: Sampling errors are surfaced clearly

    Scenario: Client rejects the request due to token limit
      Given a tool "verbose_tool" that requests an LLM completion with 100000 max tokens
      When an MCP client calls "verbose_tool"
      And the client rejects the request because the token limit exceeds its maximum
      Then the tool receives a sampling error with the client's rejection message

    Scenario: Client returns a non-text response
      Given a tool "generate" that requests an LLM completion
      When an MCP client calls "generate"
      And the client returns an image content block instead of text
      Then the tool receives a sampling error indicating a non-text response

  Rule: Abort signals cancel in-flight sampling

    Scenario: Client disconnects before completing the LLM request
      Given a tool "slow_summarize" that requests an LLM completion
      When an MCP client calls "slow_summarize"
      And the client disconnects before the LLM responds
      Then the tool receives an abort error
```

## FastMCP Parity
FastMCP (Python) exposes sampling via `ctx.sample()` which wraps the SDK's `createMessage()`. Our implementation mirrors this convenience method. FastMCP supports passing `messages` directly; we simplify with a `prompt` string parameter and offer `ctx.sampleRaw()` as an escape hatch for advanced use cases (multi-turn, image responses).

## Dependencies
- **Depends on:** CORE-007 (McpContext class) — `sample()` is a method on McpContext
- **Blocks:** none

## Technical Notes
- SDK API: `server.createMessage({ messages, maxTokens, ... })` returns `Promise<CreateMessageResult>`
- `CreateMessageResult` contains `{ content: { type: 'text', text: string } | { type: 'image', ... }, model, role, stopReason }`
- Implementation in `McpContext`:
  ```typescript
  async sample(prompt: string, options?: SamplingOptions): Promise<string> {
    if (!this.clientCapabilities?.sampling) {
      throw new McpSamplingUnsupportedError();
    }
    const result = await this.server.createMessage({
      messages: [{ role: 'user', content: { type: 'text', text: prompt } }],
      maxTokens: options?.maxTokens ?? this.defaultMaxTokens,
      temperature: options?.temperature,
      modelPreferences: options?.model ? { hints: [{ name: options.model }] } : undefined,
      systemPrompt: options?.systemPrompt,
      stopSequences: options?.stopSequences,
      includeContext: options?.includeContext,
    }, { signal: this.abortSignal });
    if (result.content.type !== 'text') {
      throw new McpSamplingError('Non-text response from sampling');
    }
    return result.content.text;
  }
  ```
- `SamplingOptions` interface:
  ```typescript
  interface SamplingOptions {
    maxTokens?: number;
    temperature?: number;
    model?: string;
    systemPrompt?: string;
    stopSequences?: string[];
    includeContext?: 'none' | 'thisServer' | 'allServers';
  }
  ```
- Consider adding `ctx.sampleRaw()` that returns the full `CreateMessageResult` for advanced use cases (image responses, stop reason inspection)
