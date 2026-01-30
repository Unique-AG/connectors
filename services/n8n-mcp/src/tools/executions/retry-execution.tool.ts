import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const RetryExecutionInput = z.object({
  id: z.number().describe('The ID of the execution to retry'),
  loadWorkflow: z
    .boolean()
    .optional()
    .describe(
      'Whether to load the currently saved workflow to execute instead of the one saved at the time of the execution. If set to true, it will retry with the latest version of the workflow.',
    ),
});

@Injectable()
export class RetryExecutionTool {
  private readonly logger = new Logger(RetryExecutionTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_retry_execution',
    title: 'Retry Execution',
    description: 'Retry a failed execution from your n8n instance.',
    parameters: RetryExecutionInput,
    annotations: {
      title: 'Retry n8n Execution',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: false,
      openWorldHint: true,
    },
  })
  @Span()
  public async retryExecution(
    { id, loadWorkflow }: z.infer<typeof RetryExecutionInput>,
    _context: Context,
  ) {
    try {
      const execution = await this.n8nApi.retryExecution(id, { loadWorkflow });
      return {
        success: true,
        execution,
      };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to retry execution',
        error: serializeError(error as Error),
        executionId: id,
      });
      throw new InternalServerErrorException(error);
    }
  }
}
