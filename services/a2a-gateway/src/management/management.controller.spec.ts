import { BadRequestException, ForbiddenException } from '@nestjs/common';
import type { Request } from 'express';
import { describe, expect, it, vi } from 'vitest';
import type { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { ManagementController } from './management.controller.js';
import type { ManagementService } from './management.service.js';

const request = {
  headers: {
    'x-company-id': 'company-1',
    'x-user-id': 'user-1',
    'x-user-roles': 'SPACE_MANAGER',
  },
} as unknown as Request;

function controller(access: unknown) {
  const management = {
    putPublication: vi.fn(),
    getPublication: vi.fn(),
    disablePublication: vi.fn(),
  };
  const unique = {
    verifySpaceManagement: vi.fn().mockResolvedValue(access),
    getAssistant: vi.fn(),
  };
  return {
    controller: new ManagementController(
      management as unknown as ManagementService,
      unique as unknown as UniqueInternalClient,
    ),
    management,
  };
}

describe('ManagementController', () => {
  it('checks object-level management access before writing', async () => {
    const subject = controller({ canWrite: false });

    await expect(
      subject.controller.putPublication(request, 'assistant-1', undefined, {
        enabled: true,
        card: {},
        skills: [],
      }),
    ).rejects.toBeInstanceOf(ForbiddenException);
    expect(subject.management.putPublication).not.toHaveBeenCalled();
  });

  it('validates publication configuration before calling the service', async () => {
    const subject = controller({ canWrite: true });

    await expect(
      subject.controller.putPublication(request, 'assistant-1', undefined, { enabled: 'yes' }),
    ).rejects.toBeInstanceOf(BadRequestException);
    expect(subject.management.putPublication).not.toHaveBeenCalled();
  });
});
