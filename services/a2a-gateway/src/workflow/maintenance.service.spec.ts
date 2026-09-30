import type { TaskContext } from 'absurd-sdk';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GatewayConfig } from '../config/config.js';
import { MaintenanceService } from './maintenance.service.js';
import type { WorkflowService } from './workflow.service.js';

function subject() {
  const workflow = { register: vi.fn(), spawn: vi.fn().mockResolvedValue({}) };
  const service = new MaintenanceService(
    workflow as unknown as WorkflowService,
    {
      reconcileIntervalSeconds: 30,
      workerEnabled: true,
    } as GatewayConfig,
  );
  service.onModuleInit();
  const handler = workflow.register.mock.calls[0]?.[1] as (
    params: { runAt: number },
    context: TaskContext,
  ) => Promise<unknown>;
  return { service, workflow, handler };
}

describe('MaintenanceService', () => {
  afterEach(() => vi.useRealTimers());

  it('schedules the next tick on the next future boundary, deduplicated by run time', async () => {
    vi.useFakeTimers({ now: 1_000_000_000_010 });
    const { service, workflow } = subject();
    await service.onApplicationBootstrap();
    expect(workflow.spawn).toHaveBeenCalledWith(
      'maintenance.tick',
      { runAt: 1_000_000_020_000 },
      { idempotencyKey: 'maintenance:1000000020000', maxAttempts: 1 },
    );
  });

  it('never schedules into the past after an outage and runs every registered job', async () => {
    vi.useFakeTimers({ now: 2_000_000_000_000 });
    const { service, workflow, handler } = subject();
    const job = vi.fn();
    const failing = vi.fn().mockRejectedValue(new Error('boom'));
    service.register('failing', failing);
    service.register('job', job);
    await handler({ runAt: 1_000_000_000_000 }, {
      sleepUntil: vi.fn(),
    } as unknown as TaskContext);
    expect(workflow.spawn).toHaveBeenCalledWith(
      'maintenance.tick',
      { runAt: 2_000_000_010_000 },
      expect.anything(),
    );
    expect(failing).toHaveBeenCalled();
    expect(job).toHaveBeenCalled();
  });
});
