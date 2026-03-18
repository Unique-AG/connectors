import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, createMeta, Tool } from '@unique-ag/mcp-server-module';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { FullSyncEventDto } from '../full-sync-event.dto';
import { FullSyncResetCommand } from '../full-sync-reset.command';

const META = createMeta({
  icon: 'refresh',
  systemPrompt:
    'Restarts the full sync from scratch. All progress is reset and a new sync version is generated. Use this when the user wants to completely redo the full sync.',
});

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  version: z.string().optional(),
});

@Injectable()
export class RestartFullSyncTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly fullSyncResetCommand: FullSyncResetCommand,
    private readonly amqp: AmqpConnection,
  ) {}

  @Tool({
    name: 'restart_full_sync',
    title: 'Restart Full Sync',
    description:
      'Restart the full sync from scratch. All progress is reset and the sync starts over.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Restart Full Sync',
      readOnlyHint: false,
      destructiveHint: true,
      idempotentHint: false,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async restartFullSync(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileTypeId = extractUserProfileId(request);

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);
    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }

    const userProfileId = userProfileTypeId.toString();
    const { version } = await this.fullSyncResetCommand.run(userProfileId);

    const event = FullSyncEventDto.parse({
      type: 'unique.outlook-semantic-mcp.full-sync.retrigger',
      payload: { userProfileId },
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);

    this.logger.log({ userProfileId, version, msg: 'Full sync restarted and retriggered' });

    return {
      success: true,
      message: `Full sync restarted with version ${version} and triggered.`,
      version,
    };
  }
}
