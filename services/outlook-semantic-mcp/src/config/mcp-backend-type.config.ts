import { asAllOptions } from '@unique-ag/utils';
import z from 'zod/v4';

export enum McpBackendType {
  MicrosoftGraphAndUniqueApi = 'MicrosoftGraphAndUniqueApi',
  MicrosoftGraph = 'MicrosoftGraph',
}

export const AllBackendTypes = asAllOptions<McpBackendType>()([
  McpBackendType.MicrosoftGraph,
  McpBackendType.MicrosoftGraphAndUniqueApi,
]);

export const mcpBackendSchema = z
  .enum(AllBackendTypes)
  .prefault(McpBackendType.MicrosoftGraphAndUniqueApi)
  .describe(
    'Selects the search backend: MicrosoftGraphAndUniqueApi (KB ingestion) or MicrosoftGraph (direct Graph search).',
  );
