import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import * as z from 'zod';
import { SubscriptionCreateService } from '../subscription-create.service';

const StartKbIntegrationInputSchema = z.object({
  dateFrom: z.string().describe('Start date for date range filter (ISO format: YYYY-MM-DD)'),
});

const StartKbIntegrationOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      expiresAt: z.string(),
      minutesUntilExpiration: z.number(),
      status: z.enum(['created', 'already_active', 'expiring_soon']),
    })
    .nullable(),
});

@Injectable()
export class StartKbIntegrationTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly subscriptionCreate: SubscriptionCreateService,
  ) {}

  @Tool({
    name: 'start_kb_integration',
    title: 'Start Knowledge Base Integration',
    description:
      'Start the knowledge base integration to begin ingesting Microsoft Outlook emails. This creates a subscription with Microsoft Graph to receive notifications when new emails are available.',
    parameters: StartKbIntegrationInputSchema,
    outputSchema: StartKbIntegrationOutputSchema,
    annotations: {
      title: 'Start Knowledge Base Integration',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt':
        'Starts the knowledge base integration for outlook emails. Use verify_kb_integration_status first to check if it is already running. If already active, inform the user that ingestion is already running.',
    },
  })
  @Span()
  public async startKbIntegration(
    input: z.infer<typeof StartKbIntegrationInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting knowledge base integration for user');

    const tid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(tid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    const result = await this.subscriptionCreate.subscribe(userProfileTypeid, input);
    const { status, subscription } = result;

    const expiresAt = new Date(subscription.expiresAt);
    const minutesUntilExpiration = Math.floor((expiresAt.getTime() - Date.now()) / (1000 * 60));

    const messages: Record<typeof status, string> = {
      created:
        'Knowledge base integration started successfully. Outlook emails will now be ingested automatically.',
      already_active: 'Knowledge base integration is already active.',
      expiring_soon: `Knowledge base integration is active but expiring in ${minutesUntilExpiration} minutes. It will be automatically renewed.`,
    };

    this.logger.log(
      { userProfileId, subscriptionId: subscription.id, status },
      'Knowledge base integration operation completed',
    );

    return {
      success: true,
      message: messages[status],
      subscription: {
        id: subscription.id,
        expiresAt: expiresAt.toISOString(),
        minutesUntilExpiration,
        status,
      },
    };
  }
}
