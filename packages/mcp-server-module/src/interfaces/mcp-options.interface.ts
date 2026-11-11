/** biome-ignore-all lint/suspicious/noExplicitAny: Fork of @rekog-labs/MCP-Nest */
import { Implementation, ServerCapabilities } from '@modelcontextprotocol/sdk/types.js';
import { CanActivate, InjectionToken, ModuleMetadata, Type } from '@nestjs/common';
import { HttpRequest } from './http-adapter.interface';

export enum McpTransportType {
  SSE = 'sse',
  STREAMABLE_HTTP = 'streamable-http',
  STDIO = 'stdio',
}

export interface McpRateLimitOptions {
  /**
   * Injection token of the server's `McpRateLimitConfig`, such as the `KEY` of
   * `registerConfig('mcpRateLimit', mcpRateLimitConfigSchema)`. It must be provided globally, as a
   * `ConfigModule` with `isGlobal: true` provides it.
   */
  config: InjectionToken;
  /** The key a tool call is counted under, such as the id of the signed-in user. */
  getRequestKey: (request: HttpRequest) => string;
}

export interface McpOptions {
  // When and if, additional properties are introduced in ServerOptions or ServerInfo,
  // consider deprecating these fields in favor of using ServerOptions and ServerInfo directly.
  name: string;
  version: string;
  capabilities?: ServerCapabilities;
  instructions?: string;
  icons?: Implementation['icons'];

  transport?: McpTransportType | McpTransportType[];
  sseEndpoint?: string;
  messagesEndpoint?: string;
  mcpEndpoint?: string;
  /**
   * @deprecated Use `app.setGlobalPrefix()` for global api prefix. Use apiPrefix to attach a prefix to the handshake.
   */
  globalApiPrefix?: never;
  apiPrefix?: string;
  guards?: Type<CanActivate>[];
  decorators?: ClassDecorator[];
  rateLimit?: McpRateLimitOptions;
  sse?: {
    pingEnabled?: boolean;
    pingIntervalMs?: number;
  };
  streamableHttp?: {
    enableJsonResponse?: boolean;
    sessionIdGenerator?: () => string;
    /**
     * @experimental: The current implementation does not fully comply with the MCP Specification.
     */
    statelessMode?: boolean;
    /** Stateful mode only: close sessions with no open request for this long. Defaults to 30 min. */
    sessionIdleTimeoutMs?: number;
  };
}

// Async variant omits transport since controllers are not auto-registered in forRootAsync
export type McpAsyncOptions = Omit<McpOptions, 'transport'>;

export interface McpOptionsFactory {
  createMcpOptions(): Promise<McpAsyncOptions> | McpAsyncOptions;
}

export interface McpModuleAsyncOptions extends Pick<ModuleMetadata, 'imports'> {
  useExisting?: Type<McpOptionsFactory>;
  useClass?: Type<McpOptionsFactory>;
  useFactory?: (...args: any[]) => Promise<McpAsyncOptions> | McpAsyncOptions;
  inject?: any[];
  extraProviders?: any[]; // allow user to provide additional providers in async mode
}
