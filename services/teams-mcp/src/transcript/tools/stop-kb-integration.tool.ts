import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { type TypeID, typeid } from 'typeid-js';
import * as z from 'zod';
import { SubscriptionRemoveService } from '../subscription-remove.service';

const StopKbIntegrationInputSchema = z.object({});

const StopKbIntegrationOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      status: z.enum(['removed', 'not_found']),
    })
    .nullable(),
});

@Injectable()
export class StopKbIntegrationTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly subscriptionRemove: SubscriptionRemoveService,
  ) {}

  @Tool({
    name: 'stop_kb_integration',
    title: 'Stop Knowledge Base Integration',
    description:
      'Stop the knowledge base integration to cease ingesting Microsoft Teams meeting transcripts. This removes the subscription with Microsoft Graph.',
    parameters: StopKbIntegrationInputSchema,
    outputSchema: StopKbIntegrationOutputSchema,
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

    const userProfileTypeid = typeid(
      'user_profile',
      userProfileId.replace('user_profile_', ''),
    ) as TypeID<'user_profile'>;

    const result = await this.subscriptionRemove.removeByUserProfileId(userProfileTypeid);
    const { status, subscription } = result;

    const messages: Record<typeof status, string> = {
      removed:
        'Knowledge base integration stopped successfully. New meeting transcripts will no longer be ingested.',
      not_found: 'Knowledge base integration is not active. Nothing to stop.',
    };

    this.logger.log(
      { userProfileId, subscriptionId: subscription?.id, status },
      'Knowledge base integration stop operation completed',
    );

    return {
      success: true,
      message: messages[status],
      subscription: subscription ? { id: subscription.id, status } : null,
    };
  }
}
