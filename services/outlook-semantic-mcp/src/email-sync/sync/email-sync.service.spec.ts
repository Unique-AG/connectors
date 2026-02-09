/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { createHash } from 'node:crypto';

import { beforeEach, describe, expect, it, vi } from 'vitest';

import { EmailSyncService } from './email-sync.service';

const TEST_SUBSCRIPTION_ID = 'sub-123';
const TEST_USER_PROFILE_ID = 'user_profile_abc';
const TEST_PROVIDER_USER_ID = 'provider-user-xyz';
const TEST_OWNER_EMAIL = 'owner@example.com';
const TEST_MESSAGE_ID = 'msg-456';
const TEST_RESOURCE = `users/${TEST_PROVIDER_USER_ID}/messages/${TEST_MESSAGE_ID}`;

const TEST_EMAIL = {
  id: 'immutable-email-id',
  internetMessageId: '<test@example.com>',
  subject: 'Test Subject',
  from: { emailAddress: { name: 'Sender', address: 'sender@example.com' } },
  toRecipients: [{ emailAddress: { name: 'To', address: 'to@example.com' } }],
  ccRecipients: [],
  receivedDateTime: '2026-02-09T10:00:00Z',
  parentFolderId: 'folder-inbox',
  conversationId: 'conv-1',
  conversationIndex: 'idx-1',
  hasAttachments: false,
  isDraft: false,
  importance: 'normal' as const,
};

const TEST_DELETED_ITEMS_FOLDER = { id: 'folder-deleteditems' };

const TEST_SUBSCRIPTION = {
  id: 'internal-id',
  subscriptionId: TEST_SUBSCRIPTION_ID,
  userProfileId: TEST_USER_PROFILE_ID,
  internalType: 'mail_monitoring',
  expiresAt: new Date(),
  createdAt: new Date(),
  updatedAt: new Date(),
};

const TEST_USER_PROFILE = {
  providerUserId: TEST_PROVIDER_USER_ID,
  email: TEST_OWNER_EMAIL,
};

const TEST_SCOPE_ID = 'scope-abc';

function computeContentHash(from: string, subject: string): string {
  return createHash('sha256').update(`${from}|${subject}`).digest('hex');
}

function createBatchResponse(emailStatus: number, emailBody: unknown, deletedItemsBody: unknown) {
  return {
    responses: [
      { id: 'email', status: emailStatus, body: emailBody },
      { id: 'deletedItems', status: 200, body: deletedItemsBody },
    ],
  };
}

function createMockEmlStream(): ReadableStream<Uint8Array<ArrayBuffer>> {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('mock-eml-content'));
      controller.close();
    },
  });
}

const mockTrace = {
  getSpan: vi.fn(() => ({
    setAttribute: vi.fn(),
    addEvent: vi.fn(),
  })),
};

const mockGraphClient = {
  api: vi.fn().mockReturnThis(),
  post: vi.fn(),
  getStream: vi.fn(),
  header: vi.fn().mockReturnThis(),
};

const mockGraphClientFactory = {
  createClientForUser: vi.fn(() => mockGraphClient),
};

const mockUniqueService = {
  ingestEmail: vi.fn(),
  deleteContent: vi.fn(),
  findContentByKey: vi.fn(),
};

const mockOnConflictDoUpdate = vi.fn();
const mockValues = vi.fn(() => ({ onConflictDoUpdate: mockOnConflictDoUpdate }));
const mockInsert = vi.fn(() => ({ values: mockValues }));
const mockDeleteWhere = vi.fn();
const mockDelete = vi.fn(() => ({ where: mockDeleteWhere }));

const mockDb = {
  query: {
    subscriptions: { findFirst: vi.fn() },
    userProfiles: { findFirst: vi.fn() },
    syncedEmails: { findFirst: vi.fn() },
  },
  insert: mockInsert,
  delete: mockDelete,
};

describe('EmailSyncService', () => {
  const service = new EmailSyncService(
    mockDb as any,
    mockGraphClientFactory as any,
    mockUniqueService as any,
    mockTrace as any,
  );

  beforeEach(() => {
    vi.clearAllMocks();

    mockDb.query.subscriptions.findFirst.mockResolvedValue(TEST_SUBSCRIPTION);
    mockDb.query.userProfiles.findFirst.mockResolvedValue(TEST_USER_PROFILE);
    mockDb.query.syncedEmails.findFirst.mockResolvedValue(undefined);

    mockGraphClient.post.mockResolvedValue(
      createBatchResponse(200, TEST_EMAIL, TEST_DELETED_ITEMS_FOLDER),
    );
    mockGraphClient.getStream.mockResolvedValue(createMockEmlStream());

    mockUniqueService.ingestEmail.mockResolvedValue({ scopeId: TEST_SCOPE_ID });

    mockGraphClient.api.mockReturnThis();
    mockGraphClient.header.mockReturnThis();
  });

  describe('syncEmail', () => {
    it('throws when subscription not found', async () => {
      mockDb.query.subscriptions.findFirst.mockResolvedValue(undefined);

      await expect(service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID)).rejects.toThrow(
        /Subscription not found/,
      );
    });

    it('throws when user profile not found', async () => {
      mockDb.query.userProfiles.findFirst.mockResolvedValue(undefined);

      await expect(service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID)).rejects.toThrow(
        /User profile not found/,
      );
    });

    it('deletes email from KB when Graph returns 404', async () => {
      mockGraphClient.post.mockResolvedValue(
        createBatchResponse(404, { error: { code: 'ErrorItemNotFound' } }, TEST_DELETED_ITEMS_FOLDER),
      );

      const cachedEmail = {
        emailId: TEST_MESSAGE_ID,
        contentKey: 'cached-content-key',
        scopeId: TEST_SCOPE_ID,
      };
      mockDb.query.syncedEmails.findFirst.mockResolvedValue(cachedEmail);

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockUniqueService.deleteContent).toHaveBeenCalledWith(
        cachedEmail.contentKey,
        cachedEmail.scopeId,
      );
      expect(mockDelete).toHaveBeenCalled();
      expect(mockDeleteWhere).toHaveBeenCalled();
    });

    it('handles 404 gracefully when no cached email exists', async () => {
      mockGraphClient.post.mockResolvedValue(
        createBatchResponse(404, { error: { code: 'ErrorItemNotFound' } }, TEST_DELETED_ITEMS_FOLDER),
      );

      mockDb.query.syncedEmails.findFirst.mockResolvedValue(undefined);

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockUniqueService.deleteContent).not.toHaveBeenCalled();
      expect(mockDelete).not.toHaveBeenCalled();
    });

    it('deletes email from KB when email is in deleted items folder', async () => {
      const emailInTrash = { ...TEST_EMAIL, parentFolderId: TEST_DELETED_ITEMS_FOLDER.id };
      mockGraphClient.post.mockResolvedValue(
        createBatchResponse(200, emailInTrash, TEST_DELETED_ITEMS_FOLDER),
      );

      const cachedEmail = {
        emailId: emailInTrash.id,
        contentKey: 'cached-content-key',
        scopeId: TEST_SCOPE_ID,
      };
      mockDb.query.syncedEmails.findFirst.mockResolvedValue(cachedEmail);

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockUniqueService.deleteContent).toHaveBeenCalledWith(
        cachedEmail.contentKey,
        cachedEmail.scopeId,
      );
      expect(mockDelete).toHaveBeenCalled();
      expect(mockDeleteWhere).toHaveBeenCalled();
    });

    it('syncs new email to knowledge base', async () => {
      mockDb.query.syncedEmails.findFirst.mockResolvedValue(undefined);

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockGraphClientFactory.createClientForUser).toHaveBeenCalledWith(TEST_USER_PROFILE_ID);
      expect(mockGraphClient.getStream).toHaveBeenCalled();
      expect(mockUniqueService.ingestEmail).toHaveBeenCalledWith(TEST_OWNER_EMAIL, {
        key: TEST_EMAIL.id,
        subject: TEST_EMAIL.subject,
        content: expect.any(ReadableStream),
        metadata: expect.objectContaining({
          subject: TEST_EMAIL.subject,
          from: TEST_EMAIL.from.emailAddress.address,
        }),
      });
      expect(mockInsert).toHaveBeenCalled();
      expect(mockValues).toHaveBeenCalled();
      expect(mockOnConflictDoUpdate).toHaveBeenCalled();
    });

    it('skips sync when email content unchanged and not a draft', async () => {
      const contentHash = computeContentHash(
        TEST_EMAIL.from.emailAddress.address,
        TEST_EMAIL.subject,
      );

      mockDb.query.syncedEmails.findFirst.mockResolvedValue({
        emailId: TEST_EMAIL.id,
        contentHash,
        scopeId: TEST_SCOPE_ID,
      });

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockUniqueService.ingestEmail).not.toHaveBeenCalled();
      expect(mockGraphClient.getStream).not.toHaveBeenCalled();
      expect(mockInsert).not.toHaveBeenCalled();
    });

    it('re-syncs email when content hash changes', async () => {
      mockDb.query.syncedEmails.findFirst.mockResolvedValue({
        emailId: TEST_EMAIL.id,
        contentHash: 'outdated-hash',
        scopeId: TEST_SCOPE_ID,
      });

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockGraphClient.getStream).toHaveBeenCalled();
      expect(mockUniqueService.ingestEmail).toHaveBeenCalledWith(TEST_OWNER_EMAIL, {
        key: TEST_EMAIL.id,
        subject: TEST_EMAIL.subject,
        content: expect.any(ReadableStream),
        metadata: expect.objectContaining({
          subject: TEST_EMAIL.subject,
          from: TEST_EMAIL.from.emailAddress.address,
        }),
      });
      expect(mockInsert).toHaveBeenCalled();
      expect(mockOnConflictDoUpdate).toHaveBeenCalled();
    });

    it('re-syncs draft email even when content hash matches', async () => {
      const draftEmail = { ...TEST_EMAIL, isDraft: true };
      mockGraphClient.post.mockResolvedValue(
        createBatchResponse(200, draftEmail, TEST_DELETED_ITEMS_FOLDER),
      );

      const contentHash = computeContentHash(
        draftEmail.from.emailAddress.address,
        draftEmail.subject,
      );

      mockDb.query.syncedEmails.findFirst.mockResolvedValue({
        emailId: draftEmail.id,
        contentHash,
        scopeId: TEST_SCOPE_ID,
      });

      await service.syncEmail(TEST_RESOURCE, TEST_SUBSCRIPTION_ID);

      expect(mockGraphClient.getStream).toHaveBeenCalled();
      expect(mockUniqueService.ingestEmail).toHaveBeenCalledWith(TEST_OWNER_EMAIL, {
        key: draftEmail.id,
        subject: draftEmail.subject,
        content: expect.any(ReadableStream),
        metadata: expect.objectContaining({
          isDraft: 'true',
        }),
      });
      expect(mockInsert).toHaveBeenCalled();
      expect(mockOnConflictDoUpdate).toHaveBeenCalled();
    });
  });
});
