import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { AppConfig, AppSettings } from '../../app-settings.enum';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const ExecuteWorkflowInput = z.object({
  workflowId: z.string().describe('The ID of the workflow to execute'),
  inputs: z
    .record(z.string(), z.unknown())
    .optional()
    .describe('Input data to pass to the workflow. The structure depends on the workflow\'s webhook configuration.'),
  waitForCompletion: z
    .boolean()
    .optional()
    .default(false)
    .describe('Whether to wait for the workflow execution to complete before returning. If false, returns immediately after triggering.'),
});

@Injectable()
export class ExecuteWorkflowTool {
  private readonly logger = new Logger(ExecuteWorkflowTool.name);
  private readonly baseUrl: string;

  public constructor(
    private readonly n8nApi: N8nApiService,
    configService: ConfigService<AppConfig, true>,
  ) {
    this.baseUrl = configService.get(AppSettings.N8N_API_URL);
  }

  @Tool({
    name: 'n8n_execute_workflow',
    title: 'Execute Workflow',
    description:
      'Execute a workflow by triggering its webhook. The workflow must be active and have at least one webhook trigger node. Returns the execution ID and optionally waits for completion.',
    parameters: ExecuteWorkflowInput,
    annotations: {
      title: 'Execute n8n Workflow',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
  })
  @Span()
  public async executeWorkflow(
    { workflowId, inputs, waitForCompletion }: z.infer<typeof ExecuteWorkflowInput>,
    _context: Context,
  ) {
    try {
      const workflow = await this.n8nApi.getWorkflow(workflowId);

      if (!workflow.active) {
        throw new Error(`Workflow ${workflowId} is not active. Activate it first before executing.`);
      }

      const webhookNode = workflow.nodes?.find(
        (node) => node.type === 'n8n-nodes-base.webhook' && !node.disabled && node.webhookId,
      );

      if (!webhookNode || !webhookNode.webhookId) {
        throw new Error(
          `Workflow ${workflowId} does not have an active webhook trigger node. Only workflows with webhook triggers can be executed via this tool.`,
        );
      }

      const webhookUrl = `${this.baseUrl}/webhook/${webhookNode.webhookId}`;

      this.logger.debug({
        msg: 'Executing workflow via webhook',
        workflowId,
        webhookId: webhookNode.webhookId,
        webhookUrl,
      });

      const response = await fetch(webhookUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(inputs || {}),
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(
          `Failed to execute workflow: ${response.status} ${response.statusText} - ${errorText}`,
        );
      }

      const executionData = await response.json().catch(() => ({}));

      if (waitForCompletion) {
        const executionId = executionData?.executionId || executionData?.id;
        if (executionId) {
          this.logger.debug({ msg: 'Waiting for execution to complete', executionId });
          const maxWaitTime = 60000;
          const startTime = Date.now();
          let execution;

          while (Date.now() - startTime < maxWaitTime) {
            await new Promise((resolve) => setTimeout(resolve, 1000));
            try {
              execution = await this.n8nApi.getExecution(executionId, { includeData: true });
              if (execution && (execution as { finished?: boolean }).finished) {
                break;
              }
            } catch (error) {
              this.logger.warn({ msg: 'Error checking execution status', error });
            }
          }

          return {
            success: true,
            executionId,
            execution,
            webhookUrl,
          };
        }
      }

      return {
        success: true,
        executionData,
        webhookUrl,
        message: waitForCompletion
          ? 'Workflow execution completed'
          : 'Workflow execution triggered successfully',
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to execute workflow',
        error: serializeError(error as Error),
        workflowId,
      });
      throw new InternalServerErrorException(error);
    }
  }
}

