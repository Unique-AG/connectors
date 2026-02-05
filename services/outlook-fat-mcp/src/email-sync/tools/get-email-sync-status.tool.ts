import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import * as z from 'zod';
import { EmailSyncService } from '../email-sync.service';

const GetEmailSyncStatusInputSchema = z.object({});

const GetEmailSyncStatusOutputSchema = z.object({
  found: z.boolean(),
  status: z.enum(['active', 'paused', 'stopped', 'not_found']),
  sync: z
    .object({
      id: z.string(),
      syncFromDate: z.string(),
      messageCount: z.number(),
      lastSyncAt: z.string().nullable(),
      lastError: z.string().nullable(),
      createdAt: z.string(),
    })
    .nullable(),
});

@Injectable()
export class GetEmailSyncStatusTool {
  private readonly logger = new Logger(GetEmailSyncStatusTool.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly emailSyncService: EmailSyncService,
  ) {}

  @Tool({
    name: 'get_email_sync_status',
    title: 'Get Email Sync Status',
    description:
      'Check the current status of email synchronization. Returns information about the sync configuration, progress, and any errors.',
    parameters: GetEmailSyncStatusInputSchema,
    outputSchema: GetEmailSyncStatusOutputSchema,
    annotations: {
      title: 'Get Email Sync Status',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'info',
      'unique.app/system-prompt':
        'Gets the current status of email synchronization. Use this to check if sync is running, paused, or stopped, and to see sync progress.',
    },
  })
  @Span()
  public async getEmailSyncStatus(
    _input: z.infer<typeof GetEmailSyncStatusInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Getting email sync status for user');

    const tid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(tid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    const result = await this.emailSyncService.getSyncStatus(userProfileTypeid);

    if (result.status === 'not_found') {
      return {
        found: false,
        status: 'not_found' as const,
        sync: null,
      };
    }

    this.logger.debug(
      { userProfileId, status: result.status, messageCount: result.messageCount },
      'Email sync status retrieved',
    );

    return {
      found: true,
      status: result.status,
      sync: result.config
        ? {
            id: result.config.id,
            syncFromDate: result.config.syncFromDate.toISOString(),
            messageCount: result.messageCount ?? 0,
            lastSyncAt: result.lastSyncAt?.toISOString() ?? null,
            lastError: result.lastError ?? null,
            createdAt: result.config.createdAt.toISOString(),
          }
        : null,
    };
  }
}
