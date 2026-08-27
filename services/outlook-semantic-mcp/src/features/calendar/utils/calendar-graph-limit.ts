import assert from 'node:assert';
import pLimit from 'p-limit';

const CALENDAR_GRAPH_CONCURRENCY = 5;

type Schedule = ReturnType<typeof pLimit>;

interface LimiterEntry {
  schedule: Schedule;
  holders: number;
}

export type CalendarGraphLimit = Schedule & Disposable;

const limiters = new Map<string, LimiterEntry>();

export function calendarGraphLimit(userId: string): CalendarGraphLimit {
  const schedule = retain(userId);
  const limit = ((fn: Parameters<Schedule>[0]) => schedule(fn)) as CalendarGraphLimit;
  limit[Symbol.dispose] = () => {
    release(userId);
  };
  return limit;
}

function retain(userId: string): Schedule {
  const existing = limiters.get(userId);
  if (existing === undefined) {
    const created = { schedule: pLimit(CALENDAR_GRAPH_CONCURRENCY), holders: 1 };
    limiters.set(userId, created);
    return created.schedule;
  }
  limiters.set(userId, { schedule: existing.schedule, holders: existing.holders + 1 });
  return existing.schedule;
}

function release(userId: string): void {
  const existing = limiters.get(userId);
  assert.ok(existing !== undefined, 'calendar Graph limiter released without a retain');
  if (existing.holders <= 1) {
    limiters.delete(userId);
    return;
  }
  limiters.set(userId, { schedule: existing.schedule, holders: existing.holders - 1 });
}
