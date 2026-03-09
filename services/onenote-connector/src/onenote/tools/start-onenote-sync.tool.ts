import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { OneNoteSyncService } from '../onenote-sync.service';

const StartSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class StartOneNoteSyncTool {
  private readonly logger = new Logger(StartOneNoteSyncTool.name);

  public constructor(private readonly syncService: OneNoteSyncService) {}

  @Tool({
    name: 'start_onenote_sync',
    title: 'Start OneNote Sync',
    description:
      'Trigger an immediate OneNote sync for the current user. Notebooks will be synced to the knowledge base.',
    parameters: z.object({}),
    outputSchema: StartSyncOutputSchema,
    annotations: {
      title: 'Start OneNote Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'refresh',
    },
  })
  @Span()
  public async startSync(
    _input: Record<string, never>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof StartSyncOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.logger.log({ userProfileId }, 'Manual sync triggered');

    await this.syncService.syncUser(userProfileId);

    return {
      success: true,
      message: 'OneNote sync completed successfully',
    };
  }
}
