import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { SubscriptionRemoveService } from '../subscription-remove.service';

const StopKbIntegrationInputSchema = z.object({});

@Injectable()
export class StopKbIntegrationTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly traceService: TraceService,
    private readonly subscriptionRemove: SubscriptionRemoveService,
  ) {}

  @Tool({
    name: 'stop_kb_integration',
    title: 'Stop Knowledge Base Integration',
    description:
      'Stop the knowledge base integration to cease ingesting Microsoft Teams meeting transcripts. This removes the subscription with Microsoft Graph.',
    parameters: StopKbIntegrationInputSchema,
    annotations: {
      title: 'Stop Knowledge Base Integration',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'stop',
      'unique.app/system-prompt':
        'Stops the knowledge base integration for meeting transcripts. After stopping, new meeting transcripts will no longer be ingested. Use verify_kb_integration_status first to check if it is running.',
    },
  })
  @Span()
  public async stopKbIntegration(
    _input: z.infer<typeof StopKbIntegrationInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Stopping knowledge base integration for user');

    // Find the existing subscription
    const existingSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId),
      ),
    });

    if (!existingSubscription) {
      this.logger.debug({ userProfileId }, 'No active knowledge base integration found for user');

      return {
        success: true,
        message: 'Knowledge base integration is not active. Nothing to stop.',
        subscription: null,
      };
    }

    // Remove the subscription by calling the service directly
    await this.subscriptionRemove.remove(existingSubscription.subscriptionId);

    this.logger.log(
      { userProfileId, subscriptionId: existingSubscription.id },
      'Successfully stopped knowledge base integration',
    );

    return {
      success: true,
      message:
        'Knowledge base integration stopped successfully. New meeting transcripts will no longer be ingested.',
      subscription: {
        id: existingSubscription.id,
        status: 'removed',
      },
    };
  }
}
