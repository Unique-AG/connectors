import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';

const VerifyInboxConnectionInputSchema = z.object({});

const SubscriptionStatusSchema = z.enum(['active', 'expiring_soon', 'expired', 'not_configured']);
type SubscriptionStatus = z.infer<typeof SubscriptionStatusSchema>;

const VerifyInboxConnectionOutputSchema = z.object({
  status: SubscriptionStatusSchema,
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      expiresAt: z.string(),
      minutesUntilExpiration: z.number(),
      createdAt: z.string(),
      updatedAt: z.string(),
    })
    .nullable(),
});

@Injectable()
export class VerifyInboxConnectionTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  @Tool({
    name: 'verify_inbox_connection',
    title: 'Verify Inbox Connection',
    description:
      'Check the status of the inbox connection for Microsoft Outlook emails. Returns whether ingestion is active, expiring soon, expired, or not configured.',
    parameters: VerifyInboxConnectionInputSchema,
    outputSchema: VerifyInboxConnectionOutputSchema,
    annotations: {
      title: 'Verify Inbox Connection',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'status',
      'unique.app/system-prompt':
        'Returns the current status of the inbox connection for outlook emails. Use this to verify if email ingestion is running before suggesting to connect or remove the inbox connection.',
    },
  })
  @Span()
  public async verifyInboxConnection(
    _input: z.infer<typeof VerifyInboxConnectionInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    traceAttrs({ user_profile_id: userProfileId });

    this.logger.debug({ userProfileId }, 'Checking inbox connection status for user');
    const userProfileTypeid = convertUserProfileIdToTypeId(userProfileId);

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'mail_monitoring'),
        eq(subscriptions.userProfileId, userProfileTypeid.toString()),
      ),
    });

    if (!subscription) {
      this.logger.debug({ userProfileId }, 'No mail subscription found for user');
      return {
        status: 'not_configured' as SubscriptionStatus,
        message: 'Inbox connection is not configured. Use connect_inbox to begin ingesting emails.',
        subscription: null,
      };
    }

    const expiresAt = new Date(subscription.expiresAt);
    const now = new Date();
    const diffFromNow = expiresAt.getTime() - now.getTime();
    const minutesUntilExpiration = Math.floor(diffFromNow / (1000 * 60));

    traceAttrs({
      'subscription.expires_at': expiresAt.toISOString(),
      'subscription.minutes_until_expiration': minutesUntilExpiration,
    });

    let status: SubscriptionStatus;
    let message: string;

    if (diffFromNow < 0) {
      status = 'expired';
      message =
        'Inbox connection subscription has expired. Use connect_inbox to restart ingestion.';
    } else if (minutesUntilExpiration <= 15) {
      status = 'expiring_soon';
      message = `Inbox connection is active but expiring in ${minutesUntilExpiration} minutes. It will be automatically renewed.`;
    } else {
      status = 'active';
      message = 'Inbox connection is active and running. Emails are being ingested.';
    }

    this.logger.debug(
      { userProfileId, status, expiresAt, minutesUntilExpiration },
      'Inbox connection status retrieved',
    );

    return {
      status,
      message,
      subscription: {
        id: subscription.id,
        expiresAt: expiresAt.toISOString(),
        minutesUntilExpiration,
        createdAt: subscription.createdAt.toISOString(),
        updatedAt: subscription.updatedAt.toISOString(),
      },
    };
  }
}
