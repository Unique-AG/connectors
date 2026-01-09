import type { EventEmitter2 } from '@nestjs/event-emitter';
import { vi } from 'vitest';

export class MockEventEmitter implements Partial<EventEmitter2> {
  public emit = vi.fn().mockReturnValue(true);
  public on = vi.fn().mockReturnThis();
  public once = vi.fn().mockReturnThis();
  public off = vi.fn().mockReturnThis();
  public removeListener = vi.fn().mockReturnThis();
  public removeAllListeners = vi.fn().mockReturnThis();
}

export const createMockEventEmitter = (): MockEventEmitter => new MockEventEmitter();
