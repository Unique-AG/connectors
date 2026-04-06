import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { PauseFullSyncCommand } from '../pause-full-sync.command';

const META = createMeta({
  icon: 'pause',
  systemPrompt:
    'Pauses the running full sync. The current batch will finish processing, then the sync stops. Use this when the user wants to temporarily halt the sync without losing progress.',
});

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class PauseFullSyncTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly pauseFullSyncCommand: PauseFullSyncCommand,
  ) {}

  @Tool({
    name: 'os_mcp_pause_full_sync',
    title: 'Pause Full Sync',
    description:
      'Pause an in-progress full sync. The current batch finishes, then the sync stops. Use `os_mcp_resume_full_sync` to continue later.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Pause Full Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async pauseFullSync(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeId = extractUserProfileId(request);

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }

    const result = await this.pauseFullSyncCommand.run(userProfileTypeId.toString());

    if (result.status === 'paused') {
      return {
        success: true,
        message: 'Full sync paused. Use `os_mcp_resume_full_sync` to continue.',
      };
    }

    if (result.status === 'not-found') {
      return { success: false, message: 'No inbox configuration found for this user.' };
    }

    return {
      success: false,
      message: `Cannot pause full sync in state "${result.currentState}". Sync can only be paused when running or waiting for ingestion.`,
    };
  }
}
