import { BadRequestException } from '@nestjs/common';
import type { Request } from 'express';
import { describe, expect, it, vi } from 'vitest';
import { ManagementController } from './management.controller.js';
import type { ManagementService } from './management.service.js';

const request = {
  headers: { 'x-company-id': 'company-1', 'x-user-id': 'user-1' },
} as unknown as Request;
function subject() {
  const management = {
    putPublication: vi.fn(),
    getPublication: vi.fn(),
    disablePublication: vi.fn(),
  };
  return {
    controller: new ManagementController(management as unknown as ManagementService),
    management,
  };
}
describe('ManagementController', () => {
  it('validates publication configuration before calling the service', async () => {
    const { controller, management } = subject();
    await expect(
      controller.putPublication(request, 'assistant-1', undefined, { enabled: 'yes' }),
    ).rejects.toBeInstanceOf(BadRequestException);
    expect(management.putPublication).not.toHaveBeenCalled();
  });
  it.each(['', '0', '-1', '"1', '1"', '1.5', '9007199254740992'])(
    'rejects invalid If-Match %s',
    async (version) => {
      await expect(
        subject().controller.putPublication(request, 'assistant-1', version, { enabled: true }),
      ).rejects.toBeInstanceOf(BadRequestException);
    },
  );
  it('derives identity from headers, not input', async () => {
    const { controller, management } = subject();
    await controller.putPublication(request, 'assistant-1', '"2"', {
      enabled: true,
      companyId: 'other',
    });
    expect(management.putPublication).toHaveBeenCalledWith(
      { companyId: 'company-1', userId: 'user-1', roles: [] },
      'assistant-1',
      { enabled: true, card: {}, skills: [] },
      2,
    );
  });
});
