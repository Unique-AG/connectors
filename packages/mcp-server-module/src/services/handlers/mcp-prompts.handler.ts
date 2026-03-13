import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  ErrorCode,
  GetPromptRequestSchema,
  ListPromptsRequestSchema,
  McpError,
  Prompt,
} from '@modelcontextprotocol/sdk/types.js';
import { Inject, Injectable, Scope } from '@nestjs/common';
import { ContextIdFactory, ModuleRef } from '@nestjs/core';
import { ZodError } from 'zod';
import { HttpRequest } from '../../interfaces/http-adapter.interface';
import { McpRegistryService } from '../mcp-registry.service';
import { McpHandlerBase } from './mcp-handler.base';

@Injectable({ scope: Scope.REQUEST })
export class McpPromptsHandler extends McpHandlerBase {
  public constructor(
    moduleRef: ModuleRef,
    registry: McpRegistryService,
    @Inject('MCP_MODULE_ID') private readonly mcpModuleId: string,
  ) {
    super(moduleRef, registry, McpPromptsHandler.name);
  }

  public registerHandlers(mcpServer: McpServer, httpRequest: HttpRequest) {
    if (this.registry.getPrompts(this.mcpModuleId).length === 0) {
      this.logger.debug('No prompts registered, skipping prompt handlers');
      return;
    }
    mcpServer.server.setRequestHandler(ListPromptsRequestSchema, () => {
      this.logger.debug('ListPromptsRequestSchema is being called');

      const prompts = this.registry.getPrompts(this.mcpModuleId).map((prompt) => {
        const promptSchema: Prompt = {
          name: prompt.metadata.name,
          description: prompt.metadata.description,
          arguments: prompt.metadata.parameters
            ? Object.entries(prompt.metadata.parameters.shape).map(([name, definition]) => ({
                name,
                description: definition.meta().description,
                required: !definition.isOptional(),
                title: definition.meta().title,
              }))
            : [],
        };

        if (prompt.metadata.title) {
          promptSchema.title = prompt.metadata.title;
        }
        if (prompt.metadata._meta) {
          promptSchema._meta = prompt.metadata._meta;
        }
        return promptSchema;
      });

      return {
        prompts,
      };
    });

    mcpServer.server.setRequestHandler(GetPromptRequestSchema, async (request) => {
      this.logger.debug('GetPromptRequestSchema is being called');

      try {
        const name = request.params.name;
        const promptInfo = this.registry.findPrompt(this.mcpModuleId, name);

        if (!promptInfo) {
          throw new McpError(ErrorCode.InvalidParams, `Invalid prompt name: ${name}`);
        }

        const contextId = ContextIdFactory.getByRequest(httpRequest);
        this.moduleRef.registerRequestByContextId(httpRequest, contextId);

        const promptInstance = await this.moduleRef.resolve(promptInfo.providerClass, contextId, {
          strict: false,
        });

        if (!promptInstance) {
          throw new McpError(
            ErrorCode.InternalError,
            `Failed to resolve prompt provider for: ${name}`,
          );
        }

        const context = this.createContext(mcpServer, request);
        const methodName = promptInfo.methodName;

        const result = await promptInstance[methodName].call(
          promptInstance,
          promptInfo.metadata.parameters
            ? promptInfo.metadata.parameters.parse(request.params.arguments)
            : {},
          context,
          httpRequest.raw,
        );

        this.logger.debug(result, 'GetPromptRequestSchema result');

        return result;
      } catch (error) {
        this.logger.error(error);
        if (error instanceof McpError) {
          throw error;
        }
        if (error instanceof ZodError) {
          const messages = (error.issues || [])
            .map((issue) => issue.message)
            .filter((msg) => !!msg);
          throw new McpError(
            ErrorCode.InvalidParams,
            messages.length > 0 ? messages.join('; ') : 'Invalid or missing arguments',
          );
        }
        throw new McpError(
          ErrorCode.InternalError,
          error instanceof Error ? error.message : String(error),
        );
      }
    });
  }
}
