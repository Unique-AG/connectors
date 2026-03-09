import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { OneNoteDeltaService } from '../onenote-delta.service';

const StopSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class StopOneNoteSyncTool {
  private readonly logger = new Logger(StopOneNoteSyncTool.name);

  public constructor(private readonly deltaService: OneNoteDeltaService) {}

  @Tool({
    name: 'stop_onenote_sync',
    title: 'Stop OneNote Sync',
    description:
      'Stop the OneNote sync for the current user. Clears the delta state so no further incremental syncs occur.',
    parameters: z.object({}),
    outputSchema: StopSyncOutputSchema,
    annotations: {
      title: 'Stop OneNote Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'stop',
    },
  })
  @Span()
  public async stopSync(
    _input: Record<string, never>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof StopSyncOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    await this.deltaService.clearDelta(userProfileId);

    this.logger.log({ userProfileId }, 'OneNote sync stopped');

    return {
      success: true,
      message: 'OneNote sync stopped. Delta state cleared.',
    };
  }
}
