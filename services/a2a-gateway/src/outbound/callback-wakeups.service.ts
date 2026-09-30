import { createHmac, timingSafeEqual } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { Inject, Injectable } from '@nestjs/common';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';

/**
 * Remote push callbacks for outbound tasks. A callback is only a hint: it is authenticated by a
 * per-execution token and wakes the runner's next poll, whose GetTask result is authoritative.
 */
@Injectable()
export class CallbackWakeups {
  private readonly waiters = new Map<string, Set<() => void>>();

  public constructor(@Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig) {}

  public token(executionId: string): string {
    return createHmac('sha256', this.config.encryptionKey)
      .update(`a2a-callback:${executionId}`)
      .digest('base64url');
  }

  public verify(executionId: string, token: string | undefined): boolean {
    const expected = Buffer.from(this.token(executionId));
    const actual = Buffer.from(token ?? '');
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  }

  public callbackUrl(executionId: string): string {
    return new URL(
      `a2a/callbacks/${encodeURIComponent(executionId)}`,
      this.config.publicBaseUrl.toString().endsWith('/')
        ? this.config.publicBaseUrl
        : `${this.config.publicBaseUrl.toString()}/`,
    ).toString();
  }

  public wake(executionId: string): void {
    for (const resolve of this.waiters.get(executionId) ?? []) {
      resolve();
    }
  }

  /** Sleeps up to `ms`, returning early when a callback for the execution arrives here. */
  public async sleep(executionId: string, ms: number, signal: AbortSignal): Promise<void> {
    const woken = new AbortController();
    const waiters = this.waiters.get(executionId) ?? new Set<() => void>();
    const resolve = (): void => woken.abort();
    waiters.add(resolve);
    this.waiters.set(executionId, waiters);
    try {
      await delay(ms, undefined, { signal: AbortSignal.any([signal, woken.signal]) });
    } catch (error) {
      if (signal.aborted) {
        throw error;
      }
    } finally {
      waiters.delete(resolve);
      if (waiters.size === 0) {
        this.waiters.delete(executionId);
      }
    }
  }
}
