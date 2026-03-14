import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { OneNoteDeltaService } from '../onenote-delta.service';

const StopSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  statusNote: z
    .string()
    .describe(
      'Human-readable status information. Always relay this to the user.',
    ),
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
      'unique.app/system-prompt':
        'Use this tool only when the user explicitly requests to disconnect or stop syncing their OneNote data. ' +
        'This is a destructive action that halts all future syncs for the user. Do not call this unprompted.',
      'unique.app/tool-format-information':
        'Always relay the statusNote to the user — it confirms what happened and what to do next.',
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

    this.logger.log({ userProfileId }, 'Tool stop_onenote_sync called');

    await this.deltaService.disableSync(userProfileId);

    this.logger.log({ userProfileId }, 'OneNote sync stopped');

    return {
      success: true,
      message: 'OneNote sync stopped for this user.',
      statusNote: 'OneNote sync has been stopped. Your notebooks will no longer be updated automatically.',
    };
  }
}
