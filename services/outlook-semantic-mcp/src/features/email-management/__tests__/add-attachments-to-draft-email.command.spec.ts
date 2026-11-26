import { beforeEach, describe, expect, it, type Mock, vi } from 'vitest';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { AddAttachmentsToDraftEmailCommand } from '../add-attachments-to-draft-email.command';

const userProfileId = convertUserProfileIdToTypeId('user_profile_01h2xcejqtf2nbrexx3vqjhp41');

describe('AddAttachmentsToDraftEmailCommand', () => {
  let findByEmail: Mock;
  let streamUniqueAttachment: { run: Mock };
  let uploadInMemoryAttachment: { run: Mock };
  let configGet: Mock;

  const commandWith = (uniqueAttachments: boolean) =>
    new AddAttachmentsToDraftEmailCommand(
      { users: { findByEmail } } as never,
      { createClientForUser: vi.fn().mockReturnValue({}) } as never,
      { run: vi.fn().mockResolvedValue({ email: 'ada@contoso.example' }) } as never,
      uploadInMemoryAttachment as never,
      streamUniqueAttachment as never,
      { get: configGet } as never,
      { uniqueAttachments } as never,
    );

  beforeEach(() => {
    findByEmail = vi.fn().mockResolvedValue({ id: 'unique-user-1', companyId: 'company-1' });
    streamUniqueAttachment = { run: vi.fn().mockResolvedValue({ status: 'success' }) };
    uploadInMemoryAttachment = { run: vi.fn().mockResolvedValue(undefined) };
    configGet = vi.fn().mockReturnValue({ enabled: true, serviceAuthMode: 'cluster_local' });
  });

  describe('with Unique attachments off', () => {
    it('refuses a unique:// file without touching Unique and still attaches a data: file', async () => {
      const result = await commandWith(false).run(userProfileId, {
        draftId: 'draft-1',
        chatId: undefined,
        attachments: [
          { fileName: 'report.pdf', data: 'unique://content/cont_report' },
          { fileName: 'notes.txt', data: 'data:text/plain;base64,aGVsbG8=' },
        ],
      });

      expect(result.attachmentsFailed).toEqual([
        {
          fileName: 'report.pdf',
          reason:
            'Files from the Unique knowledge base (unique://) are not enabled on this server. Attach the content as a data: URI instead.',
        },
      ]);
      expect(uploadInMemoryAttachment.run).toHaveBeenCalledTimes(1);
      expect(streamUniqueAttachment.run).not.toHaveBeenCalled();
      expect(findByEmail).not.toHaveBeenCalled();
      expect(configGet).not.toHaveBeenCalled();
    });
  });

  describe('with Unique attachments on', () => {
    it('streams a unique:// file from Unique as the matching Unique user', async () => {
      const result = await commandWith(true).run(userProfileId, {
        draftId: 'draft-1',
        chatId: undefined,
        attachments: [{ fileName: 'report.pdf', data: 'unique://content/cont_report' }],
      });

      expect(result.attachmentsFailed).toEqual([]);
      expect(findByEmail).toHaveBeenCalledWith('ada@contoso.example');
      expect(streamUniqueAttachment.run).toHaveBeenCalledWith(
        expect.objectContaining({
          uniqueIdentity: { userId: 'unique-user-1', companyId: 'company-1' },
        }),
      );
    });
  });
});
