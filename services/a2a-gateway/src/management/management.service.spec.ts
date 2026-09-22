import { BadRequestException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { PublicationRepository } from '../drizzle/gateway.repository.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { ManagementService } from './management.service.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: ['SPACE_MANAGER'] };

function service(assistant: unknown) {
  const publications = { upsert: vi.fn(), findByAssistant: vi.fn(), disable: vi.fn() };
  const unique = { getAssistant: vi.fn().mockResolvedValue(assistant) };
  return {
    service: new ManagementService(
      publications as unknown as PublicationRepository,
      unique as unknown as UniqueInternalClient,
    ),
    publications,
  };
}

describe('ManagementService', () => {
  it('rejects publishing an externally executed space', async () => {
    const subject = service({ executionProvider: 'A2A' });

    await expect(
      subject.service.putPublication(identity, 'assistant-1', {
        enabled: true,
        card: {},
        skills: [],
      }),
    ).rejects.toBeInstanceOf(BadRequestException);
    expect(subject.publications.upsert).not.toHaveBeenCalled();
  });

  it('maps validated publication configuration to persistence', async () => {
    const subject = service({ executionProvider: 'NATIVE' });
    subject.publications.upsert.mockResolvedValue({ id: 'pub-1' });

    await subject.service.putPublication(
      identity,
      'assistant-1',
      { enabled: true, card: { name: 'Agent' }, skills: ['search'] },
      2,
    );

    expect(subject.publications.upsert).toHaveBeenCalledWith(
      identity,
      {
        assistantId: 'assistant-1',
        enabled: true,
        cardOverrides: { name: 'Agent' },
        skills: ['search'],
      },
      2,
    );
  });
});
