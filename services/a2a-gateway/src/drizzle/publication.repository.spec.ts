import { ConflictException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { GatewayDatabase } from './drizzle.module.js';
import { PublicationRepository } from './publication.repository.js';

const principal = { companyId: 'company-1', userId: 'user-1' };
const write = {
  assistantId: 'assistant-1',
  enabled: true,
  cardOverrides: { name: 'Agent', description: 'Answers questions' },
  skills: [],
};

function repository(existing: unknown, insert = vi.fn()) {
  const update = vi.fn();
  return {
    subject: new PublicationRepository({
      query: { publications: { findFirst: vi.fn().mockResolvedValue(existing) } },
      insert,
      update,
    } as unknown as GatewayDatabase),
    update,
  };
}

describe('PublicationRepository', () => {
  it('treats a retried identical write as success without a version bump', async () => {
    const existing = { id: 'pub-1', version: 2, ...write, cardOverrides: { ...write.cardOverrides } };
    const { subject, update } = repository(existing);

    await expect(subject.upsert(principal, write, 1)).resolves.toBe(existing);
    expect(update).not.toHaveBeenCalled();
  });

  it('maps a concurrent first publication to a conflict instead of a duplicate agent', async () => {
    const insert = vi.fn().mockReturnValue({
      values: () => ({
        returning: () =>
          Promise.reject(
            new Error('insert failed', {
              cause: { code: '23505', constraint: 'a2a_publications_company_assistant_unique' },
            }),
          ),
      }),
    });
    const { subject } = repository(undefined, insert);

    await expect(subject.upsert(principal, write)).rejects.toBeInstanceOf(ConflictException);
  });
});
