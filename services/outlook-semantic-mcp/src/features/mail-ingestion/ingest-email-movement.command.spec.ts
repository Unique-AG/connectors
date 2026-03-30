/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { GraphMessage } from './dtos/microsoft-graph.dtos';
import { IngestEmailCommand } from './ingest-email.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const MESSAGE_ID = 'message_01jxk5r1s2fq9att23mp4z5ef2';
const PARENT_FOLDER_ID = 'folder_01jxk5r1s2fq9att23mp4z5ef2';
const SENT_DATE_TIME = '2024-01-15T10:00:00Z';
const LAST_MODIFIED_DATE_TIME = '2024-01-15T11:00:00Z';
const CURRENT_FOLDER_PATH = '/Inbox/Work';
const OLD_FOLDER_PATH = '/Inbox';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const graphMessage: GraphMessage = {
  id: MESSAGE_ID,
  parentFolderId: PARENT_FOLDER_ID,
  sentDateTime: SENT_DATE_TIME,
  lastModifiedDateTime: LAST_MODIFIED_DATE_TIME,
  createdDateTime: '2024-01-15T10:00:00Z',
  receivedDateTime: '2024-01-15T10:01:00Z',
  subject: 'Test Subject',
  webLink: 'https://outlook.office.com/mail/id/123',
  internetMessageId: '<test@example.com>',
  conversationId: 'conv_01',
  from: { emailAddress: { address: 'sender@example.com', name: 'Sender' } },
  sender: { emailAddress: { address: 'sender@example.com', name: 'Sender' } },
  toRecipients: [{ emailAddress: { address: 'recipient@example.com', name: 'Recipient' } }],
  ccRecipients: [],
  categories: [],
  isRead: true,
  isDraft: false,
  hasAttachments: false,
  importance: 'normal',
  inferenceClassification: 'focused',
  flag: { flagStatus: 'notFlagged' },
} as unknown as GraphMessage;

function createCommand() {
  const db = {
    query: {
      userProfiles: {
        findFirst: vi.fn().mockResolvedValue({
          id: USER_PROFILE_ID,
          email: 'user@example.com',
          providerUserId: 'provider_user_01',
        }),
      },
      directories: {
        findFirst: vi.fn().mockResolvedValue({
          id: 'dir_01',
          providerDirectoryId: PARENT_FOLDER_ID,
          displayName: 'Work',
          ignoreForSync: false,
          internalType: 'Folder',
        }),
      },
    },
  };

  const uniqueApi = {
    files: {
      getByKeys: vi.fn().mockResolvedValue([
        {
          id: 'file_01',
          metadata: {
            sentDateTime: SENT_DATE_TIME,
            lastModifiedDateTime: LAST_MODIFIED_DATE_TIME,
            emailProviderFolderPath: OLD_FOLDER_PATH,
          },
        },
      ]),
      delete: vi.fn(),
    },
    scopes: {
      getByExternalId: vi.fn().mockResolvedValue({ id: 'scope_01' }),
    },
    ingestion: {
      registerContent: vi.fn(),
      updateMetadata: vi.fn(),
      finalizeIngestion: vi.fn(),
    },
  };

  const configService = {
    get: vi.fn().mockReturnValue(false),
  };

  const graphClientFactory = {
    createClientForUser: vi.fn().mockReturnValue({}),
  };

  const getMessageDetailsQuery = {
    run: vi.fn().mockResolvedValue(graphMessage),
  };

  const uploadFileForIngestionCommand = {
    run: vi.fn(),
  };

  const upsertDirectoryCommand = {
    run: vi.fn(),
  };

  const getFolderPathsQuery = {
    run: vi.fn().mockResolvedValue({ [PARENT_FOLDER_ID]: CURRENT_FOLDER_PATH }),
  };

  const command = new IngestEmailCommand(
    db as any,
    uniqueApi as any,
    configService as any,
    graphClientFactory as any,
    getMessageDetailsQuery as any,
    uploadFileForIngestionCommand as any,
    upsertDirectoryCommand as any,
    getFolderPathsQuery as any,
  );

  vi.spyOn(command as any, 'uploadEmail').mockResolvedValue(undefined);

  return { command, mocks: { db, uniqueApi, getFolderPathsQuery } };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IngestEmailCommand movement detection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('performs full reingest when email moved to a different folder', async () => {
    const { command } = createCommand();

    const result = await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(result).toBe('ingested');
    expect((command as any).uploadEmail).toHaveBeenCalledTimes(1);
  });

  it('skips reingest when content is unchanged and folder is the same', async () => {
    const { command, mocks } = createCommand();

    mocks.uniqueApi.files.getByKeys.mockResolvedValue([
      {
        id: 'file_01',
        metadata: {
          sentDateTime: SENT_DATE_TIME,
          lastModifiedDateTime: LAST_MODIFIED_DATE_TIME,
          emailProviderFolderPath: CURRENT_FOLDER_PATH,
        },
      },
    ]);

    const result = await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(result).toBe('skipped-content-unchanged-already-ingested');
    expect((command as any).uploadEmail).not.toHaveBeenCalled();
  });

  it('resolves current folder path from getFolderPathsQuery', async () => {
    const { command, mocks } = createCommand();

    await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(mocks.getFolderPathsQuery.run).toHaveBeenCalledWith(USER_PROFILE_ID);
  });
});
