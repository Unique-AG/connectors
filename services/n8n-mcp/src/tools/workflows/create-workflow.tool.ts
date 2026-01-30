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

const CreateWorkflowInput = z.object({
  name: z.string().describe('The name of the workflow'),
  nodes: z.array(NodeSchema).describe('The nodes in the workflow'),
  connections: z.record(z.string(), z.unknown()).describe('The connections between nodes'),
  settings: WorkflowSettingsSchema.optional().describe('Workflow settings'),
});

@Injectable()
export class CreateWorkflowTool {
  private readonly logger = new Logger(CreateWorkflowTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_create_workflow',
    title: 'Create Workflow',
    description: 'Create a new workflow in your n8n instance.',
    parameters: CreateWorkflowInput,
    annotations: {
      title: 'Create n8n Workflow',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
  })
  @Span()
  public async createWorkflow(params: z.infer<typeof CreateWorkflowInput>, _context: Context) {
    try {
      const workflow = await this.n8nApi.createWorkflow(
        params as Parameters<typeof this.n8nApi.createWorkflow>[0],
      );
      return {
        success: true,
        workflow,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to create workflow',
        error: serializeError(error as Error),
      });
      throw new InternalServerErrorException(error);
    }
  }
}
