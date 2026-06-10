/** biome-ignore-all lint/suspicious/noExplicitAny: Fork of @rekog-labs/MCP-Nest */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  ElicitRequestFormParams,
  ErrorCode,
  McpError,
  Progress,
} from '@modelcontextprotocol/sdk/types.js';
import { Logger } from '@nestjs/common';
import { ModuleRef } from '@nestjs/core';
import { z } from 'zod';
import {
  Context,
  FormElicitResult,
  isDeclienOrCancelAction,
  McpRequest,
  SerializableValue,
  UrlElicitResult,
} from '../../interfaces';
import { formatZodError } from '../../utils/format-zod-error';
import { McpRegistryService } from '../mcp-registry.service';

export abstract class McpHandlerBase {
  protected logger: Logger;

  public constructor(
    protected readonly moduleRef: ModuleRef,
    protected readonly registry: McpRegistryService,
    loggerContext: string,
  ) {
    this.logger = new Logger(loggerContext);
  }

  protected createContext(mcpServer: McpServer, mcpRequest: McpRequest): Context {
    // handless stateless traffic where notifications and progress are not supported
    if ((mcpServer.server.transport as any).sessionId === undefined) {
      return this.createStatelessContext(mcpServer, mcpRequest);
    }

    const progressToken = mcpRequest.params?._meta?.progressToken;
    return {
      reportProgress: async (progress: Progress) => {
        if (progressToken) {
          await mcpServer.server.notification({
            method: 'notifications/progress',
            params: {
              ...progress,
              progressToken,
            } as Progress,
          });
        }
      },
      log: {
        debug: (message: string, context?: SerializableValue) => {
          void mcpServer.server.sendLoggingMessage({
            level: 'debug',
            data: { message, context },
          });
        },
        error: (message: string, context?: SerializableValue) => {
          void mcpServer.server.sendLoggingMessage({
            level: 'error',
            data: { message, context },
          });
        },
        info: (message: string, context?: SerializableValue) => {
          void mcpServer.server.sendLoggingMessage({
            level: 'info',
            data: { message, context },
          });
        },
        warn: (message: string, context?: SerializableValue) => {
          void mcpServer.server.sendLoggingMessage({
            level: 'warning',
            data: { message, context },
          });
        },
      },
      elicit: async <T extends z.ZodRawShape>(
        schema: z.ZodObject<T>,
        message: string,
      ): Promise<FormElicitResult<T>> => {
        const result = await mcpServer.server.elicitInput({
          message,
          requestedSchema: z.toJSONSchema(schema, {
            io: 'input',
          }) as ElicitRequestFormParams['requestedSchema'],
        });
        const action = result.action;
        if (isDeclienOrCancelAction(action)) {
          return { action, content: undefined };
        }
        // Internally the sdk uses AJV (Another JSON Validator) and will raise a McpError if z.toJSONSchema(schema, { io: 'input', })
        // validation does not pass. Once we do The z.toJSONSchema(schema, { io: 'input', }) we lose refinements and transforms from zod,
        // normally we would not need those in elicitation input but in case someone uses them we enforce zod validation and output the
        // proper requested type to the elicitation caller, after validation we raise the same McpError as the sdk validation does.
        // Examples of cases where validation would differ.
        // Cases where safeParse agrees with the SDK's AJV validation (the common case):
        // - z.string(), z.boolean(), z.number() — JSON Schema represents these exactly, AJV enforces them, Zod
        // agrees
        // - z.string().min(3) → minLength: 3 in JSON Schema — AJV enforces it, Zod agrees
        // - z.string().email() → format: "email" — AJV enforces it (with formats), Zod agrees

        // Cases where safeParse adds something AJV didn't catch:
        // - .refine(val => val.startsWith('A')) — can't be expressed in JSON Schema, AJV skips it, Zod enforces
        //  it
        // - .transform(s => s.trim()) — AJV doesn't transform, Zod would apply it
        const safeParsed = schema.safeParse(result.content);
        if (!safeParsed.success) {
          throw new McpError(ErrorCode.InvalidParams, formatZodError(safeParsed.error));
        }
        return {
          action: 'accept',
          content: schema.parse(result.content),
        };
      },
      elicitUrl: async ({
        elicitationId,
        message,
        url,
      }: {
        elicitationId: string;
        message: string;
        url: string;
      }): Promise<UrlElicitResult> => {
        const result = await mcpServer.server.elicitInput({
          mode: 'url',
          elicitationId,
          message,
          url,
        });
        const sendCompletionNotification =
          mcpServer.server.createElicitationCompletionNotifier(elicitationId);
        return { action: result.action, sendCompletionNotification };
      },
      mcpServer,
      mcpRequest,
    };
  }

  protected createStatelessContext(mcpServer: McpServer, mcpRequest: McpRequest): Context {
    const warn = (fn: string) => {
      this.logger.warn(`Stateless context: '${fn}' is not supported.`);
    };
    return {
      reportProgress: async (_progress: Progress) => {
        warn('reportProgress not supported in stateless');
      },
      log: {
        debug: (_message: string, _data?: SerializableValue) => {
          warn('server report logging not supported in stateless');
        },
        error: (_message: string, _data?: SerializableValue) => {
          warn('server report logging not supported in stateless');
        },
        info: (_message: string, _data?: SerializableValue) => {
          warn('server report logging not supported in stateless');
        },
        warn: (_message: string, _data?: SerializableValue) => {
          warn('server report logging not supported in stateless');
        },
      },
      elicit: async () => {
        throw new McpError(ErrorCode.InternalError, 'elicit is not supported in stateless mode');
      },
      elicitUrl: async () => {
        throw new McpError(ErrorCode.InternalError, 'elicitUrl is not supported in stateless mode');
      },
      mcpServer,
      mcpRequest,
    };
  }
}
