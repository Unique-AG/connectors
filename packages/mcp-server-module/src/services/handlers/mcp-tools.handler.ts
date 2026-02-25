/** biome-ignore-all lint/suspicious/noExplicitAny: Fork of @rekog-labs/MCP-Nest */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import {
  CallToolRequestSchema,
  ErrorCode,
  ListToolsRequestSchema,
  McpError,
  Tool,
} from '@modelcontextprotocol/sdk/types.js';
import { Inject, Injectable, Scope } from '@nestjs/common';
import { ContextIdFactory, ModuleRef } from '@nestjs/core';
import * as z from 'zod';
import { HttpRequest } from '../../interfaces/http-adapter.interface';
import { McpRegistryService } from '../mcp-registry.service';
import { McpHandlerBase } from './mcp-handler.base';

@Injectable({ scope: Scope.REQUEST })
export class McpToolsHandler extends McpHandlerBase {
  public constructor(
    moduleRef: ModuleRef,
    registry: McpRegistryService,
    @Inject('MCP_MODULE_ID') private readonly mcpModuleId: string,
  ) {
    super(moduleRef, registry, McpToolsHandler.name);
  }

  private buildDefaultContentBlock(result: any) {
    return [
      {
        type: 'text',
        text: JSON.stringify(result, null, 2),
      },
    ];
  }

  private formatToolResult(result: any, outputSchema?: z.ZodTypeAny): any {
    if (result && typeof result === 'object' && Array.isArray(result.content)) {
      return result;
    }

    if (outputSchema) {
      const validation = outputSchema.safeParse(result);
      if (!validation.success) {
        throw new McpError(
          ErrorCode.InternalError,
          `Tool result does not match outputSchema: ${validation.error.message}`,
        );
      }
      return {
        structuredContent: result,
        content: this.buildDefaultContentBlock(result),
      };
    }

    return {
      content: this.buildDefaultContentBlock(result),
    };
  }

  public registerHandlers(mcpServer: McpServer, httpRequest: HttpRequest) {
    if (this.registry.getTools(this.mcpModuleId).length === 0) {
      this.logger.debug('No tools registered, skipping tool handlers');
      return;
    }

    mcpServer.server.setRequestHandler(ListToolsRequestSchema, () => {
      const tools = this.registry.getTools(this.mcpModuleId).map((tool) => {
        const toolSchema: Tool = {
          name: tool.metadata.name,
          description: tool.metadata.description,
          annotations: tool.metadata.annotations,
          // Zod's toJSONSchema does not correctly infer the 'type' field for the schema. Hence the type assertion.
          inputSchema: z.toJSONSchema(tool.metadata.parameters, {
            io: 'input',
          }) as Tool['inputSchema'],
        };

        if (tool.metadata.title) toolSchema.title = tool.metadata.title;
        if (tool.metadata._meta) toolSchema._meta = tool.metadata._meta;
        if (tool.metadata.outputSchema)
          toolSchema.outputSchema = z.toJSONSchema(
            tool.metadata.outputSchema,
          ) as Tool['outputSchema'];

        return toolSchema;
      });

      return {
        tools,
      };
    });

    mcpServer.server.setRequestHandler(CallToolRequestSchema, async (request) => {
      this.logger.debug('CallToolRequestSchema is being called');

      const toolInfo = this.registry.findTool(this.mcpModuleId, request.params.name);

      if (!toolInfo) {
        throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
      }

      try {
        // Validate input parameters against the tool's schema
        if (toolInfo.metadata.parameters) {
          const validation = toolInfo.metadata.parameters.safeParse(request.params.arguments || {});
          if (!validation.success) {
            throw new McpError(
              ErrorCode.InvalidParams,
              `Invalid parameters: ${validation.error.message}`,
            );
          }
          // Use validated arguments to ensure defaults and transformations are applied
          request.params.arguments = validation.data;
        }

        const contextId = ContextIdFactory.getByRequest(httpRequest);
        this.moduleRef.registerRequestByContextId(httpRequest, contextId);

        const toolInstance = await this.moduleRef.resolve(toolInfo.providerClass, contextId, {
          strict: false,
        });

        const context = this.createContext(mcpServer, request);

        if (!toolInstance) {
          throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${request.params.name}`);
        }

        const result = await toolInstance[toolInfo.methodName].call(
          toolInstance,
          request.params.arguments,
          context,
          httpRequest.raw,
        );

        const transformedResult = this.formatToolResult(result, toolInfo.metadata.outputSchema);

        this.logger.debug('CallToolRequestSchema result');

        return transformedResult;
      } catch (error) {
        this.logger.error(error);
        // Re-throw McpErrors (like validation errors) so they are handled by the MCP protocol layer
        if (error instanceof McpError) {
          throw error;
        }
        // For other errors, return formatted error response
        return {
          content: [{ type: 'text', text: error instanceof Error ? error.message : String(error) }],
          isError: true,
        };
      }
    });
  }
}
