import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { Inject, Injectable, Scope } from '@nestjs/common';
import { ModuleRef } from '@nestjs/core';
import { HttpRequest } from '../interfaces/http-adapter.interface';
import { McpPromptsHandler } from './handlers/mcp-prompts.handler';
import { McpResourcesHandler } from './handlers/mcp-resources.handler';
import { McpToolsHandler } from './handlers/mcp-tools.handler';
import { McpRegistryService } from './mcp-registry.service';
import { RateLimiterService } from './rate-limiter.service';

/**
 * Request-scoped service for executing MCP tools
 */
@Injectable({ scope: Scope.REQUEST })
export class McpExecutorService {
  private toolsHandler: McpToolsHandler;
  private resourcesHandler: McpResourcesHandler;
  private promptsHandler: McpPromptsHandler;

  public constructor(
    moduleRef: ModuleRef,
    registry: McpRegistryService,
    @Inject('MCP_MODULE_ID') mcpModuleId: string,
    rateLimiter: RateLimiterService,
  ) {
    this.toolsHandler = new McpToolsHandler(moduleRef, registry, mcpModuleId, rateLimiter);
    this.resourcesHandler = new McpResourcesHandler(moduleRef, registry, mcpModuleId);
    this.promptsHandler = new McpPromptsHandler(moduleRef, registry, mcpModuleId);
  }

  /**
   * Register tool-related request handlers with the MCP server
   * @param mcpServer - The MCP server instance
   * @param request - The current HTTP request object
   */
  public registerRequestHandlers(mcpServer: McpServer, httpRequest: HttpRequest) {
    this.toolsHandler.registerHandlers(mcpServer, httpRequest);
    this.resourcesHandler.registerHandlers(mcpServer, httpRequest);
    this.promptsHandler.registerHandlers(mcpServer, httpRequest);
  }
}
