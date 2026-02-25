import assert from 'node:assert';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import { FullSyncCommand } from '~/email-sync/full-sync/full-sync.command';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';

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
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId }, 'Starting directory sync');
    const subscription = await this.drizzle.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });
    assert.ok(subscription, `Missing subscription for userProfile: ${userProfileId}`);

    await this.fullSyncCommand.run(subscription.subscriptionId);

    return OutputSchema.encode({
      success: true,
      message: `Successfully run`,
    });
  }
}
