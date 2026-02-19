import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from '../sync-directories.command';

const InputSchema = z.object({});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
});

@Injectable()
export class RunDirectorySyncTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Tool({
    name: 'run_directories_sync',
    title: 'Run directories sync',
    description: 'Run directories sync',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'Run directories sync',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'play',
      'unique.app/system-prompt': 'Starts directories in database',
    },
  })
  @Span()
  public async startKbIntegration(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);

    this.logger.log({ userProfileId }, 'Starting directory sync');
    const userProfileTypeid = convertUserProfileIdToTypeId(userProfileId);

    await this.syncDirectoriesCommand.run(userProfileTypeid);

    return {
      success: true,
      message: `Successfully run`,
    };
  }
}
