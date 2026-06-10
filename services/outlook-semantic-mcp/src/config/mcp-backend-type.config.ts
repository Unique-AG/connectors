import { asAllOptions } from '@unique-ag/utils';
import z from 'zod/v4';

export enum McpBackendType {
  MicrosoftGraphAndUniqueApi = 'microsoft_graph_and_unique_api',
  MicrosoftGraph = 'microsoft_graph',
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
