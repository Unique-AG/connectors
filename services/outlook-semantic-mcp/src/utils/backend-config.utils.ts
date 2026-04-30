import { mcpBackendSchema, mcpDebugModeSchema } from '~/config/app.config';

export const isMicrosoftGraphBackend = (): boolean =>
  mcpBackendSchema.parse(process.env.MCP_BACKEND) === 'MicrosoftGraph';

export const isDebugMode = (): boolean => mcpDebugModeSchema.parse(process.env.MCP_DEBUG_MODE);
