import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const ListExecutionsInput = z.object({
  includeData: z
    .boolean()
    .optional()
    .describe("Whether or not to include the execution's detailed data"),
  status: z
    .enum(['canceled', 'error', 'running', 'success', 'waiting'])
    .optional()
    .describe('Status to filter the executions by'),
  workflowId: z.string().optional().describe('Workflow ID to filter the executions by'),
  projectId: z.string().optional().describe('Project ID to filter the executions by'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(250)
    .prefault(100)
    .describe('Maximum number of executions to return'),
  cursor: z.string().optional().describe('Pagination cursor from previous request'),
});

@Injectable()
export class ListExecutionsTool {
  private readonly logger = new Logger(ListExecutionsTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_list_executions',
    title: 'List Executions',
    description:
      'Retrieve all executions from your n8n instance. Supports filtering by status, workflow, and project.',
    parameters: ListExecutionsInput,
    annotations: {
      title: 'List n8n Executions',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  })
  @Span()
  public async listExecutions(params: z.infer<typeof ListExecutionsInput>, _context: Context) {
    try {
      const result = await this.n8nApi.getExecutions(params);
      return {
        executions: result.data,
        nextCursor: result.nextCursor,
        count: result.data.length,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to list executions',
        error: serializeError(error as Error),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
