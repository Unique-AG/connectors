import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const ListWorkflowsInput = z.object({
  active: z.boolean().optional().describe('Filter by active status'),
  tags: z.string().optional().describe('Comma-separated list of tag names to filter by'),
  name: z.string().optional().describe('Filter by workflow name'),
  projectId: z.string().optional().describe('Filter by project ID'),
  excludePinnedData: z.boolean().optional().describe('Set this to avoid retrieving pinned data'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(250)
    .prefault(100)
    .describe('Maximum number of workflows to return'),
  cursor: z.string().optional().describe('Pagination cursor from previous request'),
});

@Injectable()
export class ListWorkflowsTool {
  private readonly logger = new Logger(ListWorkflowsTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_list_workflows',
    title: 'List Workflows',
    description:
      'Retrieve all workflows from your n8n instance. Supports filtering by active status, tags, name, and project.',
    parameters: ListWorkflowsInput,
    annotations: {
      title: 'List n8n Workflows',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  })
  @Span()
  public async listWorkflows(params: z.infer<typeof ListWorkflowsInput>, _context: Context) {
    try {
      const result = await this.n8nApi.getWorkflows(params);
      return {
        workflows: result.data,
        nextCursor: result.nextCursor,
        count: result.data.length,
      };
    } catch (error) {
      this.logger.error({ msg: 'Failed to list workflows', error: serializeError(error as Error) });
      throw new InternalServerErrorException(error);
    }
  }
}
