import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const NodeSchema = z.object({
  id: z.string().optional(),
  name: z.string().optional(),
  type: z.string().optional(),
  typeVersion: z.number().optional(),
  position: z.array(z.number()).optional(),
  parameters: z.record(z.string(), z.unknown()).optional(),
  credentials: z.record(z.string(), z.unknown()).optional(),
});

const WorkflowSettingsSchema = z.object({
  saveExecutionProgress: z.boolean().optional(),
  saveManualExecutions: z.boolean().optional(),
  saveDataErrorExecution: z.enum(['all', 'none']).optional(),
  saveDataSuccessExecution: z.enum(['all', 'none']).optional(),
  executionTimeout: z.number().max(3600).optional(),
  timezone: z.string().optional(),
});

const UpdateWorkflowInput = z.object({
  id: z.string().describe('The ID of the workflow to update'),
  name: z.string().describe('The name of the workflow'),
  nodes: z.array(NodeSchema).describe('The nodes in the workflow'),
  connections: z.record(z.string(), z.unknown()).describe('The connections between nodes'),
  settings: WorkflowSettingsSchema.optional().describe('Workflow settings'),
});

@Injectable()
export class UpdateWorkflowTool {
  private readonly logger = new Logger(UpdateWorkflowTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_update_workflow',
    title: 'Update Workflow',
    description:
      'Update an existing workflow in your n8n instance. If the workflow is published, the updated version will be automatically re-published.',
    parameters: UpdateWorkflowInput,
    annotations: {
      title: 'Update n8n Workflow',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  })
  @Span()
  public async updateWorkflow(
    { id, ...workflowData }: z.infer<typeof UpdateWorkflowInput>,
    _context: Context,
  ) {
    try {
      const workflow = await this.n8nApi.updateWorkflow(
        id,
        workflowData as Parameters<typeof this.n8nApi.updateWorkflow>[1],
      );
      return {
        success: true,
        workflow,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to update workflow',
        error: serializeError(error as Error),
        workflowId: id,
      });
      throw new InternalServerErrorException(error);
    }
  }
}
