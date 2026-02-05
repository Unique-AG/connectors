import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import * as z from 'zod';
import { EmailSyncService } from '../email-sync.service';

const StartEmailSyncInputSchema = z.object({
  syncFromDate: z
    .string()
    .describe('ISO 8601 date string. Only emails received after this date will be synced.')
    .refine((val) => !Number.isNaN(Date.parse(val)), {
      message: 'Invalid date format. Please use ISO 8601 format (e.g., 2024-01-01)',
    }),
});

const StartEmailSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  sync: z
    .object({
      id: z.string(),
      status: z.enum(['created', 'already_active', 'resumed']),
      syncFromDate: z.string(),
      createdAt: z.string(),
    })
    .nullable(),
});

@Injectable()
export class StartEmailSyncTool {
  private readonly logger = new Logger(StartEmailSyncTool.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly emailSyncService: EmailSyncService,
  ) {}

  @Tool({
    name: 'start_email_sync',
    title: 'Start Email Sync',
    description:
      'Start syncing Outlook emails to the knowledge base. This will begin ingesting emails received after the specified date. The sync runs automatically at scheduled intervals.',
    parameters: StartEmailSyncInputSchema,
    outputSchema: StartEmailSyncOutputSchema,
    annotations: {
      title: 'Start Email Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'mail',
      'unique.app/system-prompt':
        'Starts email synchronization to the knowledge base. Use get_email_sync_status first to check if sync is already running. Requires a date to filter which emails to sync.',
    },
  })
  @Span()
  public async startEmailSync(
    input: z.infer<typeof StartEmailSyncInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting email sync for user');

    const tid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(tid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    const syncFromDate = new Date(input.syncFromDate);
    const result = await this.emailSyncService.startSync(userProfileTypeid, syncFromDate);

    const messages: Record<typeof result.status, string> = {
      created: 'Email sync started successfully. Emails will be synced automatically.',
      already_active: 'Email sync is already active.',
      resumed: 'Email sync has been resumed.',
    };

    this.logger.log(
      { userProfileId, configId: result.config.id, status: result.status },
      'Email sync operation completed',
    );

    return {
      success: true,
      message: messages[result.status],
      sync: {
        id: result.config.id,
        status: result.status,
        syncFromDate: result.config.syncFromDate.toISOString(),
        createdAt: result.config.createdAt.toISOString(),
      },
    };
  }
}
