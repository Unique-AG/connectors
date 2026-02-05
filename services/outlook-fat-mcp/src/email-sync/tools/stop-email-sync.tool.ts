import type { McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import * as z from 'zod';
import { EmailSyncService } from '../email-sync.service';

const StopEmailSyncInputSchema = z.object({});

const StopEmailSyncOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class StopEmailSyncTool {
  private readonly logger = new Logger(StopEmailSyncTool.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly emailSyncService: EmailSyncService,
  ) {}

  @Tool({
    name: 'stop_email_sync',
    title: 'Stop Email Sync',
    description:
      'Stop the email synchronization. This will pause all email ingestion. You can restart sync later using start_email_sync.',
    parameters: StopEmailSyncInputSchema,
    outputSchema: StopEmailSyncOutputSchema,
    annotations: {
      title: 'Stop Email Sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'stop',
      'unique.app/system-prompt':
        'Stops email synchronization. Use get_email_sync_status first to check if sync is running before stopping it.',
    },
  })
  @Span()
  public async stopEmailSync(
    _input: z.infer<typeof StopEmailSyncInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Stopping email sync for user');

    const tid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(tid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    const result = await this.emailSyncService.stopSync(userProfileTypeid);

    if (result.status === 'not_found') {
      return {
        success: false,
        message: 'No email sync configuration found. Nothing to stop.',
      };
    }

    this.logger.log({ userProfileId }, 'Email sync stopped successfully');

    return {
      success: true,
      message: 'Email sync has been stopped. You can restart it using start_email_sync.',
    };
  }
}
