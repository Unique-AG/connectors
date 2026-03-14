import { type Context, type Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';

interface UserThrottleState {
  retryAfterMs: number;
  accumulatedWaitMs: number;
}

export class GlobalThrottleMiddleware implements Middleware {
  private static readonly logger = new Logger('GlobalThrottleMiddleware');
  private static readonly userThrottles = new Map<string, UserThrottleState>();
  private nextMiddleware: Middleware | undefined;

  public constructor(private readonly userProfileId: string) {}

  private static getOrCreate(userProfileId: string): UserThrottleState {
    let state = GlobalThrottleMiddleware.userThrottles.get(userProfileId);
    if (!state) {
      state = { retryAfterMs: 0, accumulatedWaitMs: 0 };
      GlobalThrottleMiddleware.userThrottles.set(userProfileId, state);
    }
    return state;
  }

  public static snapshotWaitMs(userProfileId: string): number {
    return GlobalThrottleMiddleware.getOrCreate(userProfileId).accumulatedWaitMs;
  }

  public static currentThrottleRemainingMs(userProfileId: string): number {
    const remaining = GlobalThrottleMiddleware.getOrCreate(userProfileId).retryAfterMs - Date.now();
    return remaining > 0 ? remaining : 0;
  }

  public static buildStatusNote(userProfileId: string, throttleWaitMs: number, extras: string[] = []): string | undefined {
    const parts: string[] = [];

    if (throttleWaitMs > 0) {
      const seconds = Math.round(throttleWaitMs / 1000);
      parts.push(
        `This request was delayed by ~${seconds}s because Microsoft OneNote is temporarily rate-limiting requests. ` +
        'This is normal during heavy usage and resolves on its own.',
      );
    }

    const remainingMs = GlobalThrottleMiddleware.currentThrottleRemainingMs(userProfileId);
    if (remainingMs > 0) {
      const remainingSec = Math.round(remainingMs / 1000);
      parts.push(
        `OneNote API is still rate-limited — subsequent requests may be delayed by up to ${remainingSec}s.`,
      );
    }

    parts.push(...extras);

    return parts.length > 0 ? parts.join(' ') : undefined;
  }

  public static activateThrottle(userProfileId: string, delayMs: number): void {
    const state = GlobalThrottleMiddleware.getOrCreate(userProfileId);
    const newRetryAfter = Date.now() + delayMs;
    if (newRetryAfter > state.retryAfterMs) {
      state.retryAfterMs = newRetryAfter;
      GlobalThrottleMiddleware.logger.warn(
        { userProfileId, delayMs, retryUntil: new Date(newRetryAfter).toISOString() },
        'Per-user throttle activated from thrown error — Graph requests for this user will wait',
      );
    }
  }

  private getWaitMs(): number {
    return GlobalThrottleMiddleware.currentThrottleRemainingMs(this.userProfileId);
  }

  private updateThrottle(response: Response): void {
    if (response.status !== 429 && response.status !== 503) return;

    const retryAfterHeader = response.headers.get('Retry-After');
    let delayMs = 10_000;

    if (retryAfterHeader) {
      const seconds = Number(retryAfterHeader);
      if (!Number.isNaN(seconds)) {
        delayMs = seconds * 1000;
      } else {
        const date = Date.parse(retryAfterHeader);
        if (!Number.isNaN(date)) {
          delayMs = Math.max(date - Date.now(), 1000);
        }
      }
    }

    const state = GlobalThrottleMiddleware.getOrCreate(this.userProfileId);
    const newRetryAfter = Date.now() + delayMs;
    if (newRetryAfter > state.retryAfterMs) {
      state.retryAfterMs = newRetryAfter;
      GlobalThrottleMiddleware.logger.warn(
        { userProfileId: this.userProfileId, delayMs, retryAfterHeader, retryUntil: new Date(newRetryAfter).toISOString() },
        'Per-user throttle activated — Graph requests for this user will wait',
      );
    }
  }

  private static sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    const waitMs = this.getWaitMs();
    if (waitMs > 0) {
      GlobalThrottleMiddleware.logger.log(
        { waitMs, userProfileId: this.userProfileId },
        'Request waiting due to per-user Graph API throttle',
      );
      await GlobalThrottleMiddleware.sleep(waitMs);
      GlobalThrottleMiddleware.getOrCreate(this.userProfileId).accumulatedWaitMs += waitMs;
    }

    await this.nextMiddleware.execute(context);

    if (context.response) {
      this.updateThrottle(context.response);
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }
}
