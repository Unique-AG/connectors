import type { ExecutionContext } from '@nestjs/common';
import type { McpIdentity } from './mcp-identity.interface';

/**
 * Extracts McpIdentity from an ExecutionContext.
 * Returns null for non-MCP contexts or unauthenticated requests.
 *
 * Note: Full implementation pending CORE-009 (McpExecutionContextHost).
 * Currently returns null for all contexts until switchToMcp() is available.
 */
export function getMcpIdentity(_context: ExecutionContext): McpIdentity | null {
  // TODO: implement once CORE-009 provides context.switchToMcp()
  // return context.getType() === 'mcp'
  //   ? context.switchToMcp().getMcpContext().identity
  //   : null;
  return null;
}
