import { ConfigService } from '@nestjs/config';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  type AddAttachmentsInput,
  AddAttachmentsToDraftEmailCommand,
} from './add-attachments-to-draft-email.command';
import { UniqueConfigNamespaced } from '../../config';

const USER_PROFILE_ID = { toString: () => 'user_profile_test123' } as unknown as UserProfileTypeID;
const DRAFT_ID = 'draft-abc-123';

const CLUSTER_LOCAL_CONFIG = {
  serviceAuthMode: 'cluster_local' as const,
  ingestionServiceBaseUrl: 'https://ingestion.example.com',
};

const EXTERNAL_CONFIG = {
  serviceAuthMode: 'external' as const,
  ingestionServiceBaseUrl: 'https://ingestion.example.com',
};

function makeMockGraphClient() {
  return {
    api: vi.fn().mockReturnValue({
      post: vi.fn().mockResolvedValue({ uploadUrl: 'https://upload.example.com/session' }),
    }),
  };
}

function createCommand(overrides?: {
  config?: Record<string, unknown>;
  profileEmail?: string;
  findByEmailResult?: { id: string; email: string; companyId: string } | null;
}) {
  const mockGraphClient = makeMockGraphClient();

  const graphClientFactory = {
    createClientForUser: () => mockGraphClient,
  } as unknown as GraphClientFactory;

  const getUserProfileQuery = {
    run: vi.fn().mockResolvedValue({ email: overrides?.profileEmail ?? 'user@example.com' }),
  };

  const uniqueApiClient = {
    users: {
      findByEmail: vi
        .fn()
        .mockResolvedValue(
          overrides?.findByEmailResult !== undefined
            ? overrides.findByEmailResult
            : { id: 'unique-user-42', email: 'user@example.com', companyId: 'comp-1' },
        ),
    },
  };

  const configService = {
    get: vi.fn().mockReturnValue(overrides?.config ?? CLUSTER_LOCAL_CONFIG),
  } as unknown as ConfigService<UniqueConfigNamespaced, true>;

  const command = new AddAttachmentsToDraftEmailCommand(
    graphClientFactory,
    // biome-ignore lint/suspicious/noExplicitAny: test mock
    getUserProfileQuery as any,
    // biome-ignore lint/suspicious/noExplicitAny: test mock
    uniqueApiClient as any,
    configService,
  );

  return { command, mockGraphClient, getUserProfileQuery, uniqueApiClient, configService };
}

describe('AddAttachmentsToDraftEmailCommand', () => {
  let fetchSpy: { mockRestore(): void } | undefined;

  afterEach(() => {
    fetchSpy?.mockRestore();
  });

  describe('data: URI attachments', () => {
    it('uploads base64 data URI as inline attachment for small files', async () => {
      const { command, mockGraphClient } = createCommand();
      const base64Content = Buffer.from('hello').toString('base64');
      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: [`data:text/plain;base64,${base64Content}`],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(0);
      expect(mockGraphClient.api).toHaveBeenCalledWith(`/me/messages/${DRAFT_ID}/attachments`);
    });
  });

  describe('unique:// URI attachments', () => {
    it('reports failure when not in cluster_local mode', async () => {
      const { command } = createCommand({ config: EXTERNAL_CONFIG });
      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['unique://chat/chat_1/content/cont_abc'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toEqual([
        {
          uri: 'unique://chat/chat_1/content/cont_abc',
          reason: 'App is not running in cluster local',
        },
      ]);
    });

    it('reports failure for unique URI with empty chatId segment', async () => {
      const { command } = createCommand();
      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['unique://chat//content/cont_abc'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(1);
      expect(result.attachmentsFailed?.[0]?.reason).toBe('Missing chatId for unique:// attachment');
    });

    it('resolves user identity and downloads content in cluster_local mode', async () => {
      const { command, getUserProfileQuery, uniqueApiClient } = createCommand();
      const fileContent = Buffer.from('pdf-content');
      fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(
        new Response(fileContent, {
          status: 200,
          headers: { 'content-disposition': 'attachment; filename="report.pdf"' },
        }),
      );

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['unique://chat/chat_1/content/cont_abc'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(0);
      expect(getUserProfileQuery.run).toHaveBeenCalledWith(USER_PROFILE_ID);
      expect(uniqueApiClient.users.findByEmail).toHaveBeenCalledWith('user@example.com');
      expect(fetchSpy).toHaveBeenCalledWith(
        'https://ingestion.example.com/v1/content/cont_abc/file',
        {
          headers: {
            'x-user-id': 'unique-user-42',
            'x-company-id': 'comp-1',
            'x-service-id': 'outlook-semantic-mcp',
          },
        },
      );
    });

    it('reports failure when unique user is not found', async () => {
      const { command } = createCommand({ findByEmailResult: null });

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['unique://chat/chat_1/content/cont_abc'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toEqual([
        {
          uri: 'unique://chat/chat_1/content/cont_abc',
          reason: 'Could not resolve unique identity',
        },
      ]);
    });

    it('reuses resolved identity for multiple unique:// attachments', async () => {
      const { command, getUserProfileQuery, uniqueApiClient } = createCommand();
      fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(new Response(Buffer.from('file1'), { status: 200 }))
        .mockResolvedValueOnce(new Response(Buffer.from('file2'), { status: 200 }));

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['unique://chat/chat_1/content/cont_a', 'unique://chat/chat_1/content/cont_b'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(0);
      expect(getUserProfileQuery.run).toHaveBeenCalledTimes(1);
      expect(uniqueApiClient.users.findByEmail).toHaveBeenCalledTimes(1);
    });
  });

  describe('https:// URL attachments', () => {
    it('downloads and uploads external URL content', async () => {
      const { command } = createCommand();
      fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(new Response(Buffer.from('external-file'), { status: 200 }));

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['https://example.com/files/document.pdf'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(0);
      expect(fetchSpy).toHaveBeenCalledWith('https://example.com/files/document.pdf');
    });

    it('reports failure when external URL returns non-200', async () => {
      const { command } = createCommand();
      fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(new Response('Not Found', { status: 404 }));

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['https://example.com/missing.pdf'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toEqual([
        { uri: 'https://example.com/missing.pdf', reason: 'URL download failed (404)' },
      ]);
    });
  });

  describe('unsupported URIs', () => {
    it('reports failure for unsupported URI schemes', async () => {
      const { command } = createCommand();
      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: ['ftp://example.com/file.pdf'],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(1);
      expect(result.attachmentsFailed[0]?.uri).toBe('ftp://example.com/file.pdf');
    });
  });

  describe('mixed attachments', () => {
    it('processes different URI types and reports individual failures', async () => {
      const { command } = createCommand();
      const base64Content = Buffer.from('inline-data').toString('base64');
      fetchSpy = vi
        .spyOn(globalThis, 'fetch')
        .mockResolvedValueOnce(new Response(Buffer.from('unique-content'), { status: 200 }))
        .mockResolvedValueOnce(new Response('Forbidden', { status: 403 }));

      const input: AddAttachmentsInput = {
        draftId: DRAFT_ID,
        attachments: [
          `data:text/plain;base64,${base64Content}`,
          'unique://chat/chat_1/content/cont_ok',
          'https://example.com/forbidden.pdf',
        ],
      };

      const result = await command.run(USER_PROFILE_ID, input);

      expect(result.attachmentsFailed).toHaveLength(1);
      expect(result.attachmentsFailed[0]?.uri).toBe('https://example.com/forbidden.pdf');
    });
  });
});
