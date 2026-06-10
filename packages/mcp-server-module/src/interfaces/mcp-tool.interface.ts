import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  CallToolRequest,
  GetPromptRequest,
  Progress,
  ReadResourceRequest,
} from '@modelcontextprotocol/sdk/types.js';
import { z } from 'zod';

export type Literal = boolean | null | number | string | undefined;

export type SerializableValue =
  | Literal
  | SerializableValue[]
  | { [key: string]: SerializableValue };

export type McpRequest = CallToolRequest | ReadResourceRequest | GetPromptRequest;

export const isDeclienOrCancelAction = (action: string): action is 'cancel' | 'decline' =>
  ['cancel', 'decline'].includes(action);

export type FormElicitResult<T extends z.ZodRawShape> =
  | { action: 'accept'; content: z.infer<z.ZodObject<T>> }
  | { action: 'decline' | 'cancel'; content?: undefined };

export interface UrlElicitResult {
  action: 'accept' | 'decline' | 'cancel';
  sendCompletionNotification: () => Promise<void>;
}

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
  elicit<T extends z.ZodRawShape>(
    schema: z.ZodObject<T>,
    message: string,
  ): Promise<FormElicitResult<T>>;
  elicitUrl(params: {
    elicitationId: string;
    message: string;
    url: string;
  }): Promise<UrlElicitResult>;
  mcpServer: McpServer;
  mcpRequest: McpRequest;
}
