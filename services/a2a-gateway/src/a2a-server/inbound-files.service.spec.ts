import { NotFoundException } from '@nestjs/common';
import { describe, expect, it, vi } from 'vitest';
import type { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import type { GatewayConfig } from '../config/config.js';
import type { ContextRepository } from '../drizzle/context.repository.js';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { InboundFilesService } from './inbound-files.service.js';
import { fileUrlFor, outcomeArtifacts } from './inbound-translation.js';
import type { PgTaskStore } from './pg-task.store.js';

const identity = { companyId: 'company-1', userId: 'user-1', roles: [] };
const fileUrl = fileUrlFor(new URL('https://gateway.example/'), 'pub-1', 'task-1');

const completed = outcomeArtifacts(
  'task-1',
  {
    kind: 'completed',
    message: {
      id: 'msg-1',
      text: 'See the chart ![chart](unique://content/cont_chart) and the report.',
      references: [{ name: 'report.pdf', url: 'unique://content/cont_report', sequenceNumber: 1 }],
    },
  },
  fileUrl,
);

function subject() {
  const contexts = {
    findTask: vi.fn().mockResolvedValue({
      companyId: 'company-1',
      userId: 'user-1',
      chatId: 'chat-1',
      publicationId: 'pub-1',
    }),
  };
  const authorization = { publication: vi.fn() };
  const unique = {
    downloadContent: vi.fn().mockResolvedValue({
      bytes: Buffer.from('pdf'),
      mimeType: 'application/pdf',
      filename: '../report.pdf',
    }),
  };
  const service = new InboundFilesService(
    authorization as unknown as ResourceAuthorizationService,
    contexts as unknown as ContextRepository,
    {
      findSnapshot: vi.fn().mockResolvedValue({ id: 'task-1', artifacts: completed }),
    } as unknown as PgTaskStore,
    unique as unknown as UniqueInternalClient,
    { maxRemoteFileBytes: 1024 } as GatewayConfig,
  );
  return { service, contexts, authorization, unique };
}

describe('inbound file artifacts', () => {
  it('exposes linked and cited chat content through task-bound gateway URLs', () => {
    const files = completed.find((artifact) => artifact.artifactId === 'files-task-1');
    expect(files?.parts.map((part) => [part.filename, part.content])).toEqual([
      [
        'report.pdf',
        {
          $case: 'url',
          value: 'https://gateway.example/a2a/agents/pub-1/files/cont_report?taskId=task-1',
        },
      ],
      [
        'cont_chart',
        {
          $case: 'url',
          value: 'https://gateway.example/a2a/agents/pub-1/files/cont_chart?taskId=task-1',
        },
      ],
    ]);
  });

  it('downloads an exposed file under the owner identity with a safe name', async () => {
    const { service, unique, authorization } = subject();
    const file = await service.download(identity, 'pub-1', 'task-1', 'cont_report');
    expect(authorization.publication).toHaveBeenCalledWith(identity, 'pub-1');
    expect(unique.downloadContent).toHaveBeenCalledWith(identity, 'cont_report', 'chat-1', 1024);
    expect(file.filename).toBe('report.pdf');
  });

  it.each([
    ['another user', { ...identity, userId: 'user-2' }, 'pub-1', 'cont_report'],
    ['another tenant', { ...identity, companyId: 'company-2' }, 'pub-1', 'cont_report'],
    ['another publication', identity, 'pub-2', 'cont_report'],
    ['content the task did not expose', identity, 'pub-1', 'cont_other'],
  ])('refuses %s', async (_case, caller, publicationId, contentId) => {
    const { service, unique } = subject();
    await expect(
      service.download(caller, publicationId, 'task-1', contentId),
    ).rejects.toBeInstanceOf(NotFoundException);
    expect(unique.downloadContent).not.toHaveBeenCalled();
  });
});
