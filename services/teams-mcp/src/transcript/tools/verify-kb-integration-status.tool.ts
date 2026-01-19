import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';

const VerifyKbIntegrationStatusInputSchema = z.object({});

type SubscriptionStatus = 'active' | 'expiring_soon' | 'expired' | 'not_configured';

@Injectable()
export class VerifyKbIntegrationStatusTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'verify_kb_integration_status',
    title: 'Verify Knowledge Base Integration Status',
    description:
      'Check the status of the knowledge base integration for Microsoft Teams meeting transcripts. Returns whether ingestion is active, expiring soon, expired, or not configured.',
    parameters: VerifyKbIntegrationStatusInputSchema,
    annotations: {
      title: 'Verify Knowledge Base Integration Status',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'status',
      'unique.app/system-prompt':
        'Returns the current status of the knowledge base integration for meeting transcripts. Use this to verify if transcription ingestion is running before suggesting to start or stop it.',
    },
  })
  @Span()
  public async verifyKbIntegrationStatus(
    _input: z.infer<typeof VerifyKbIntegrationStatusInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.debug({ userProfileId }, 'Checking knowledge base integration status for user');

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId),
      ),
    });

    if (!subscription) {
      this.logger.debug({ userProfileId }, 'No transcript subscription found for user');
      return {
        status: 'not_configured' as SubscriptionStatus,
        message:
          'Knowledge base integration is not configured. Use start_kb_integration to begin ingesting meeting transcripts.',
        subscription: null,
      };
    }

    const expiresAt = new Date(subscription.expiresAt);
    const now = new Date();
    const diffFromNow = expiresAt.getTime() - now.getTime();
    const minutesUntilExpiration = Math.floor(diffFromNow / (1000 * 60));

    span?.setAttribute('subscription.expires_at', expiresAt.toISOString());
    span?.setAttribute('subscription.minutes_until_expiration', minutesUntilExpiration);

    let status: SubscriptionStatus;
    let message: string;

    if (diffFromNow < 0) {
      status = 'expired';
      message =
        'Knowledge base integration subscription has expired. Use start_kb_integration to restart ingestion.';
    } else if (minutesUntilExpiration <= 15) {
      status = 'expiring_soon';
      message = `Knowledge base integration is active but expiring in ${minutesUntilExpiration} minutes. It will be automatically renewed.`;
    } else {
      status = 'active';
      message =
        'Knowledge base integration is active and running. Meeting transcripts are being ingested.';
    }

    this.logger.debug(
      { userProfileId, status, expiresAt, minutesUntilExpiration },
      'Knowledge base integration status retrieved',
    );

    return {
      status,
      message,
      subscription: {
        id: subscription.id,
        expiresAt: expiresAt.toISOString(),
        minutesUntilExpiration,
        createdAt: subscription.createdAt,
        updatedAt: subscription.updatedAt,
      },
    };
  }
}
