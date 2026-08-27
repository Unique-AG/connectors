import { calendarIntegrationSchema, mcpBackendSchema, mcpDebugModeSchema } from '~/config';

export const isMicrosoftGraphBackend = (): boolean =>
  mcpBackendSchema.parse(process.env.MCP_BACKEND) === 'microsoft_graph';

export const isDebugMode = (): boolean => mcpDebugModeSchema.parse(process.env.MCP_DEBUG_MODE);

export const isCalendarEnabled = (): boolean =>
  calendarIntegrationSchema.parse(process.env.CALENDAR_INTEGRATION);
