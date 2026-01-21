import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Inject, Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { type TypeID, typeid } from 'typeid-js';
import * as z from 'zod';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { SubscriptionCreateService } from '../subscription-create.service';

const StartKbIntegrationInputSchema = z.object({});

const StartKbIntegrationOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  subscription: z
    .object({
      id: z.string(),
      expiresAt: z.string(),
      minutesUntilExpiration: z.number(),
      status: z.enum(['created', 'already_active']),
    })
    .nullable(),
});

@Injectable()
export class StartKbIntegrationTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly traceService: TraceService,
    private readonly subscriptionCreate: SubscriptionCreateService,
  ) {}

  @Tool({
    name: 'start_kb_integration',
    title: 'Start Knowledge Base Integration',
    description:
      'Start the knowledge base integration to begin ingesting Microsoft Teams meeting transcripts. This creates a subscription with Microsoft Graph to receive notifications when new transcripts are available.',
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
        'Starts the knowledge base integration for meeting transcripts. Use verify_kb_integration_status first to check if it is already running. If already active, inform the user that ingestion is already running.',
    },
  })
  @Span()
  public async startKbIntegration(
    _input: z.infer<typeof StartKbIntegrationInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting knowledge base integration for user');

    // Check if subscription already exists and is valid
    const existingSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId),
      ),
    });

    if (existingSubscription) {
      const expiresAt = new Date(existingSubscription.expiresAt);
      const now = new Date();
      const diffFromNow = expiresAt.getTime() - now.getTime();
      const minutesUntilExpiration = Math.floor(diffFromNow / (1000 * 60));

      // Subscription is still valid (more than 15 minutes until expiration)
      if (diffFromNow > 15 * 60 * 1000) {
        this.logger.debug(
          { userProfileId, subscriptionId: existingSubscription.id },
          'Knowledge base integration already active for user',
        );

        return {
          success: true,
          message: 'Knowledge base integration is already active.',
          subscription: {
            id: existingSubscription.id,
            expiresAt: expiresAt.toISOString(),
            minutesUntilExpiration,
            status: 'already_active',
          },
        };
      }
    }

    // Create new subscription by calling the service directly
    const userProfileTypeid = typeid(
      'user_profile',
      userProfileId.replace('user_profile_', ''),
    ) as TypeID<'user_profile'>;
    await this.subscriptionCreate.subscribe(userProfileTypeid);

    // Fetch the newly created subscription
    const newSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId),
      ),
    });

    if (!newSubscription) {
      this.logger.error(
        { userProfileId },
        'Failed to create knowledge base integration subscription',
      );
      return {
        success: false,
        message: 'Failed to start knowledge base integration. Please try again.',
        subscription: null,
      };
    }

    const expiresAt = new Date(newSubscription.expiresAt);
    const minutesUntilExpiration = Math.floor((expiresAt.getTime() - Date.now()) / (1000 * 60));

    this.logger.log(
      { userProfileId, subscriptionId: newSubscription.id },
      'Successfully started knowledge base integration',
    );

    return {
      success: true,
      message:
        'Knowledge base integration started successfully. Meeting transcripts will now be ingested automatically.',
      subscription: {
        id: newSubscription.id,
        expiresAt: expiresAt.toISOString(),
        minutesUntilExpiration,
        status: 'created',
      },
    };
  }
}
