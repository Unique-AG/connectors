import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { N8nApiService } from '../../n8n-api/n8n-api.service';

const GetExecutionInput = z.object({
  id: z.number().describe('The ID of the execution to retrieve'),
  includeData: z
    .boolean()
    .optional()
    .describe("Whether or not to include the execution's detailed data"),
});

@Injectable()
export class GetExecutionTool {
  private readonly logger = new Logger(GetExecutionTool.name);

  public constructor(private readonly n8nApi: N8nApiService) {}

  @Tool({
    name: 'n8n_get_execution',
    title: 'Get Execution',
    description: 'Retrieve a specific execution by its ID from your n8n instance.',
    parameters: GetExecutionInput,
    annotations: {
      title: 'Get n8n Execution',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
  })
  @Span()
  public async getExecution(
    { id, includeData }: z.infer<typeof GetExecutionInput>,
    _context: Context,
  ) {
    try {
      const execution = await this.n8nApi.getExecution(id, { includeData });
      return { execution };
    } catch (error) {
      this.logger.error({
        msg: 'Failed to get execution',
        error: serializeError(error as Error),
        executionId: id,
      });
      throw new InternalServerErrorException(error);
    }
  }
}
