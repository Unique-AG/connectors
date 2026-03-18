import assert from 'node:assert';
import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import {
  FullSyncRunStatus,
  StartFullSyncCommand,
} from '~/features/sync/full-sync/start-full-sync.command';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';

const META = createMeta({
  icon: 'play',
  systemPrompt:
    "Triggers a full re-sync of the user's Outlook inbox. Use this when the user reports missing emails, stale search results, or after a long period of inactivity. After triggering, call `sync_progress` to monitor ingestion status.",
});

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
    private readonly startFullSyncCommand: StartFullSyncCommand,
  ) {}

  @Tool({
    name: 'run_full_sync',
    title: 'Run Full Sync',
    description:
      'Trigger a full re-sync of the Outlook mailbox into the knowledge base. Skips if a sync was run recently. Use `sync_progress` to monitor ingestion status after triggering.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Run Full Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async startKbIntegration(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeid = extractUserProfileId(request);
    const userProfileId = userProfileTypeid.toString();

    this.logger.log({ userProfileId, msg: 'Starting directory sync' });
    const subscription = await this.drizzle.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfileId),
    });
    assert.ok(subscription, `Missing subscription for userProfile: ${userProfileId}`);

    const { status } = await this.startFullSyncCommand.run(subscription.subscriptionId);

    const responseByStatus: Record<FullSyncRunStatus, { success: boolean; message: string }> = {
      skipped: { success: false, message: `Skipped running full sync, it was run recently` },
      started: { success: true, message: `Full sync started` },
    };

    return responseByStatus[status];
  }
}
