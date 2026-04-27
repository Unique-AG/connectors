import { mcpBackendSchema, mcpDebugModeSchema } from '~/config/app.config';

export const isGraphBackend = (): boolean =>
  mcpBackendSchema.parse(process.env.MCP_BACKEND) === 'MicrosoftGraph';

export const isDebugMode = (): boolean => mcpDebugModeSchema.parse(process.env.MCP_DEBUG_MODE);
