import { ForbiddenException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { PublicationService } from './publication.service.js';

const identity: RequestIdentity = {
  companyId: 'company-1',
  userId: 'user-1',
  roles: [],
};

const card = {
  name: 'Research agent',
  description: 'Answers research questions',
  documentationUrl: 'https://docs.example/agent',
};

const publication = {
  id: 'pub-1',
  assistantId: 'assistant-1',
  version: 3,
  cardOverrides: card,
  skills: [
    {
      id: 'research',
      name: 'Research',
      description: 'Research a topic',
      tags: ['research'],
      examples: ['Research this company'],
    },
  ],
};

function service(
  publications: {
    findEnabledById?: ReturnType<typeof vi.fn>;
    listEnabled?: ReturnType<typeof vi.fn>;
  },
  useSpace = vi.fn().mockResolvedValue(undefined),
): PublicationService {
  return new PublicationService(
    {
      publicBaseUrl: new URL('https://gateway.example/base/'),
      zitadelIssuer: new URL('https://identity.example/'),
    } as never,
    { useSpace } as never,
    publications as never,
  );
}

describe('PublicationService', () => {
  it('builds a public A2A 1.0 card without tenant internals', async () => {
    const subject = service({ findEnabledById: vi.fn().mockResolvedValue(publication) });

    const result = await subject.getAgentCard('pub-1');

    expect(result.supportedInterfaces).toEqual([
      expect.objectContaining({
        protocolBinding: 'JSONRPC',
        protocolVersion: '1.0',
        url: 'https://gateway.example/base/a2a/agents/pub-1',
      }),
    ]);
    expect(result.skills).toEqual([expect.objectContaining({ id: 'research' })]);
    expect(JSON.stringify(result)).not.toContain('assistant-1');
    expect(JSON.stringify(result)).not.toContain('company-1');
  });

  it('returns only publications the current user may use', async () => {
    const useSpace = vi.fn().mockImplementation((_identity, assistantId: string) => {
      if (assistantId === 'assistant-denied') {
        throw new ForbiddenException();
      }
    });
    const subject = service(
      {
        listEnabled: vi
          .fn()
          .mockResolvedValue([
            publication,
            { ...publication, id: 'pub-denied', assistantId: 'assistant-denied' },
          ]),
      },
      useSpace,
    );

    await expect(subject.catalog(identity)).resolves.toEqual([
      expect.objectContaining({ publicationId: 'pub-1', name: 'Research agent' }),
    ]);
    expect(useSpace).toHaveBeenCalledTimes(2);
  });
});
