import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { SyncDirectoriesForSubscriptionsCommand } from '../sync-directories-for-subscriptions.command';

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class RunDirectorySyncTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly syncDirectoriesForSubscriptionsCommand: SyncDirectoriesForSubscriptionsCommand,
  ) {}

  @Tool({
    name: 'run_directories_sync_for_all',
    title: 'Run directories sync for all subscriptions',
    description: 'Run directories sync for all subscriptions',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Run directories sync for all subscriptions',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt':
        'Starts directories sync for last 10 users which synscronized a long time ago',
    },
  })
  @Span()
  public async startKbIntegration(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting directory sync');

    try {
      await this.syncDirectoriesForSubscriptionsCommand.run();
    } catch (error) {
      await this.logger.error(error);
      return { success: false, message: `Failed to run sync` };
    }

    return {
      success: true,
      message: `Successfully run`,
    };
  }
}
