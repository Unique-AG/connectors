import { mcpDebugModeSchema } from '~/config/app.config';
import { mcpBackendSchema } from '~/config/mcp-backend-type.config';

export const isMicrosoftGraphBackend = (): boolean =>
  mcpBackendSchema.parse(process.env.MCP_BACKEND) === 'MicrosoftGraph';

export const isDebugMode = (): boolean => mcpDebugModeSchema.parse(process.env.MCP_DEBUG_MODE);
