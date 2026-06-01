import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { extractUserProfileId } from '~/utils/extract-user-profile-id';
import {
  ListMailboxesAndDirectoriesQuery,
  type UserDirectory,
  type UserMailbox,
} from '../../user-utils/list-mailboxes-and-directories.query';
import { SyncDirectoriesCommand } from '../sync-directories.command';
import { META } from './list-mailboxes-and-directories-tool.meta';

const InputSchema = z.object({});

const UserDirectorySchema: z.ZodType<UserDirectory> = z.lazy(() =>
  z.object({
    id: z
      .string()
      .describe('Opaque folder ID — pass this to the email search tool to filter by folder.'),
    displayName: z.string().describe('Human-readable folder name.'),
    canReadContent: z
      .boolean()
      .describe(
        'Whether this folder can be searched. Always true for own mailboxes. For delegated mailboxes, true means explicitly shared; false means the folder is a structural ancestor only and cannot be searched.',
      ),
    children: z.array(UserDirectorySchema).describe('Nested sub-folders, may be empty.'),
  }),
);

const UserMailboxSchema: z.ZodType<UserMailbox> = z.object({
  ownerId: z.string().describe('Internal user profile ID of the mailbox owner.'),
  email: z
    .string()
    .nullable()
    .describe('Email address of the mailbox owner, or null if unavailable.'),
  displayName: z
    .string()
    .nullable()
    .describe('Display name of the mailbox owner, or null if unavailable.'),
  hasFullAccess: z
    .boolean()
    .describe(
      "True when the user has full delegated access to this mailbox (or it's their own), false when only specific folders were shared.",
    ),
  isOwn: z
    .boolean()
    .describe("True for the user's own primary mailbox, false for delegated (shared) mailboxes."),
  folders: z
    .array(UserDirectorySchema)
    .describe('Top-level folders. Each folder may contain nested children.'),
});

const OutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  status: z.string().optional(),
  mailboxes: z
    .array(UserMailboxSchema)
    .optional()
    .describe(
      'List of mailboxes the user has access to, including their own and any delegated mailboxes.',
    ),
});

@Injectable()
export class ListMailboxesAndDirectoriesTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
    private readonly listDirectoriesQuery: ListMailboxesAndDirectoriesQuery,
  ) {}

  @Tool({
    name: 'list_mailboxes_and_directories',
    title: 'List Mailboxes and Directories',
    description:
      "List all Outlook mailboxes with their folders/directories available for the user. Returns the user's own mailbox and any delegated (shared) mailboxes they have access to. Each mailbox contains a hierarchical folder tree. Each folder has an id that can be passed to the `directories` filter in `search_emails`.",
    parameters: InputSchema,
    outputSchema: OutputSchema,
    annotations: {
      title: 'List Mailboxes and Directories',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: META,
  })
  @Span()
  public async list(
    _input: z.infer<typeof InputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<
    | { success: boolean; message: string }
    | { success: boolean; message: string; mailboxes: UserMailbox[] }
  > {
    const userProfileTypeId = extractUserProfileId(request);
    const userProfileTypeIdString = userProfileTypeId.toString();
    this.logger.log({
      userProfileId: userProfileTypeIdString,
      msg: 'Running directory sync before listing mailboxes and directories',
    });
    await this.syncDirectoriesCommand.run(userProfileTypeId);
    const mailboxes = await this.listDirectoriesQuery.run(userProfileTypeIdString);

    return {
      success: true,
      message: 'Directories available',
      mailboxes,
    };
  }
}
