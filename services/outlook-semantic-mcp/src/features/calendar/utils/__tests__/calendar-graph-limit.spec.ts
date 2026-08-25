import { describe, expect, it } from 'vitest';
import { calendarGraphLimit } from '../calendar-graph-limit';

describe(calendarGraphLimit.name, () => {
  it('shares one concurrency queue across overlapping using blocks', async () => {
    using first = calendarGraphLimit('user-share');
    using second = calendarGraphLimit('user-share');
    let releaseHold: (() => void) | undefined;
    const hold = new Promise<void>((resolve) => {
      releaseHold = resolve;
    });
    let inFlight = 0;
    let maxInFlight = 0;

    const work = async (): Promise<void> => {
      inFlight += 1;
      maxInFlight = Math.max(maxInFlight, inFlight);
      await hold;
      inFlight -= 1;
    };

    const running = Promise.all([
      ...Array.from({ length: 4 }, () => first(work)),
      ...Array.from({ length: 4 }, () => second(work)),
    ]);
    await Promise.resolve();
    expect(maxInFlight).toBe(5);
    releaseHold?.();
    await running;
  });

  it('drops the limiter once the last holder finishes', async () => {
    let previous: unknown;
    {
      using limit = calendarGraphLimit('user-2');
      previous = limit;
    }
    {
      using limit = calendarGraphLimit('user-2');
      expect(limit).not.toBe(previous);
    }
  });
});
