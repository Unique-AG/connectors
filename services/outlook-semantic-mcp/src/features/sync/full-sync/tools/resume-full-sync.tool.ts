import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ResumeFullSyncCommand } from '../resume-full-sync.command';

const META = createMeta({
  icon: 'play',
  systemPrompt:
    'Resumes a paused full sync. The sync will continue from where it left off. Use this after the user has paused a sync and wants to continue.',
});

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class ResumeFullSyncTool {
  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly resumeFullSyncCommand: ResumeFullSyncCommand,
  ) {}

  @Tool({
    name: 'resume_full_sync',
    title: 'Resume Full Sync',
    description:
      'Resume a paused full sync. The sync continues from where it left off. Use `sync_progress` to monitor progress.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Resume Full Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async resumeFullSync(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeId = extractUserProfileId(request);

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }

    const result = await this.resumeFullSyncCommand.run(userProfileTypeId.toString());

    if (result.status === 'resumed') {
      return {
        success: true,
        message: 'Full sync resumed. Use `sync_progress` to monitor progress.',
      };
    }

    if (result.status === 'not-found') {
      return { success: false, message: 'No inbox configuration found for this user.' };
    }

    return {
      success: false,
      message: `Cannot resume full sync in state "${result.currentState}". Sync can only be resumed when paused.`,
    };
  }
}
