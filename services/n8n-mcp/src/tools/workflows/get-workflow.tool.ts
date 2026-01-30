import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const GetWorkflowInput = z.object({
  id: z.string().describe('The ID of the workflow to retrieve'),
  excludePinnedData: z.boolean().optional().describe('Set this to avoid retrieving pinned data'),
});

@Injectable()
export class GetWorkflowTool {
  private readonly logger = new Logger(GetWorkflowTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_get_workflow',
    title: 'Get Workflow',
    description: 'Retrieve a specific workflow by its ID from your n8n instance.',
    parameters: GetWorkflowInput,
    annotations: {
      title: 'Get n8n Workflow',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  })
  @Span()
  public async getWorkflow(
    { id, excludePinnedData }: z.infer<typeof GetWorkflowInput>,
    _context: Context,
  ) {
    try {
      const workflow = await this.n8nApi.getWorkflow(id, { excludePinnedData });
      return { workflow };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to get workflow',
        error: serializeError(error as Error),
        workflowId: id,
      });
      throw new InternalServerErrorException(error);
    }
  }
}
