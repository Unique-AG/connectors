import assert from 'node:assert';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/drizzle';
import { FullSyncCommand } from '~/email-sync/mail-injestion/full-sync.command';

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class RunFullSyncTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly drizzle: DrizzleDatabase,
    private readonly traceService: TraceService,
    private readonly fullSyncCommand: FullSyncCommand,
  ) {}

  @Tool({
    name: 'run_full_sync',
    title: 'Run Full Sync',
    description: 'Run Full Sync',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Run Full Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt': 'Starts full sync',
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
    const subscription = await this.drizzle.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });
    assert.ok(subscription, `Missing subscription for userProfile: ${userProfileId}`);

    try {
      await this.fullSyncCommand.run(subscription?.subscriptionId);
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
