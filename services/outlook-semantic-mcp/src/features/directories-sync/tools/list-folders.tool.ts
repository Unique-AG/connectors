import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GetSubscriptionStatusQuery } from '~/features/subscriptions/get-subscription-status.query';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import { ListDirectoriesQuery, type UserDirectory } from '../list-directories.query';
import { SyncDirectoriesCommand } from '../sync-directories.command';
import { META } from './list-folders-tool.meta';

const InputSchema = z.object({});

const UserDirectorySchema: z.ZodType<UserDirectory> = z.lazy(() =>
  z.object({
    id: z.string(),
    displayName: z.string(),
    children: z.array(UserDirectorySchema),
  }),
);

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  status: z.string().optional(),
  folders: z.array(UserDirectorySchema).optional(),
});

@Injectable()
export class ListFoldersTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly getSubscriptionStatusQuery: GetSubscriptionStatusQuery,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    private readonly listDirectoriesQuery: ListDirectoriesQuery,
  ) {}

  @Tool({
    name: 'list_folders',
    title: 'List Folders',
    description:
      'List all Outlook mail folders available for the user. Returns a hierarchical tree of folders (e.g. Inbox, Sent, custom folders). Each folder has an id that can be passed to the `directories` filter in `search_emails`.',
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'List Folders',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: META,
  })
  @Span()
  public async listFolders(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<
    | { success: boolean; message: string }
    | { success: boolean; message: string; folders: UserDirectory[] }
  > {
    const userProfileTypeId = extractUserProfileId(request);
    const userProfileTypeIdString = userProfileTypeId.toString();

    const subscriptionStatus = await this.getSubscriptionStatusQuery.run(userProfileTypeId);

    if (!subscriptionStatus.success) {
      return subscriptionStatus;
    }

    this.logger.log({
      userProfileId: userProfileTypeIdString,
      msg: 'Running directory sync before listing folders',
    });
    await this.syncDirectoriesCommand.run(userProfileTypeId);

    const folders = await this.listDirectoriesQuery.run(userProfileTypeIdString);

    return {
      success: true,
      message: 'Directories available',
      folders,
    };
  }
}
