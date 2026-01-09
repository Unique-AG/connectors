import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  CallToolRequest,
  GetPromptRequest,
  Progress,
  ReadResourceRequest,
} from '@modelcontextprotocol/sdk/types.js';

export type Literal = boolean | null | number | string | undefined;

export type SerializableValue =
  | Literal
  | SerializableValue[]
  | { [key: string]: SerializableValue };

export type McpRequest = CallToolRequest | ReadResourceRequest | GetPromptRequest;

/**
 * Enhanced execution context that includes user information
 */
export interface Context {
  reportProgress: (progress: Progress) => Promise<void>;
  log: {
    debug: (message: string, data?: SerializableValue) => void;
    error: (message: string, data?: SerializableValue) => void;
    info: (message: string, data?: SerializableValue) => void;
    warn: (message: string, data?: SerializableValue) => void;
  };
  mcpServer: McpServer;
  mcpRequest: McpRequest;
}
