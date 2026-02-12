import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { elapsedMilliseconds, elapsedSeconds, elapsedSecondsLog } from '../timing';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('elapsedMilliseconds', () => {
  it('returns elapsed milliseconds from a Date', () => {
    const start = new Date();
    vi.advanceTimersByTime(1500);

    expect(elapsedMilliseconds(start)).toBe(1500);
  });

  it('returns elapsed milliseconds from a timestamp number', () => {
    vi.setSystemTime(10_000);
    const startTimestamp = 5000;
    vi.advanceTimersByTime(2500);

    expect(elapsedMilliseconds(startTimestamp)).toBe(7500);
  });

  it('returns positive number for past times', () => {
    vi.setSystemTime(1000);
    const startTimestamp = 500;

    expect(elapsedMilliseconds(startTimestamp)).toBe(500);
  });
});

describe('elapsedSeconds', () => {
  it('returns milliseconds divided by 1000', () => {
    const start = new Date();
    vi.advanceTimersByTime(2345);

    expect(elapsedSeconds(start)).toBe(2.345);
  });

  it('returns zero when no time has elapsed', () => {
    const start = new Date();

    expect(elapsedSeconds(start)).toBe(0);
  });

  it('returns elapsed seconds from a timestamp number', () => {
    vi.setSystemTime(1000);
    const startTimestamp = 500;
    vi.advanceTimersByTime(1500);

    expect(elapsedSeconds(startTimestamp)).toBe(2);
  });
});

describe('elapsedSecondsLog', () => {
  it('returns formatted string with two decimal places and s suffix', () => {
    const start = new Date();
    vi.advanceTimersByTime(1230);

    expect(elapsedSecondsLog(start)).toBe('1.23s');
  });

  it('rounds to two decimal places', () => {
    const start = new Date();
    vi.advanceTimersByTime(1999);

    expect(elapsedSecondsLog(start)).toBe('2.00s');
  });

  it('returns formatted string from a timestamp number', () => {
    vi.setSystemTime(1000);
    const startTimestamp = 500;
    vi.advanceTimersByTime(1230);

    expect(elapsedSecondsLog(startTimestamp)).toBe('1.73s');
  });
});
