import { afterEach, describe, expect, it } from 'vitest';
import { isCalendarEnabled } from '../backend-config.utils';

describe(isCalendarEnabled.name, () => {
  const original = process.env.CALENDAR_INTEGRATION;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.CALENDAR_INTEGRATION;
    } else {
      process.env.CALENDAR_INTEGRATION = original;
    }
  });

  it('defaults to disabled when CALENDAR_INTEGRATION is unset', () => {
    delete process.env.CALENDAR_INTEGRATION;
    expect(isCalendarEnabled()).toBe(false);
  });

  it('is enabled when CALENDAR_INTEGRATION=enabled', () => {
    process.env.CALENDAR_INTEGRATION = 'enabled';
    expect(isCalendarEnabled()).toBe(true);
  });

  it('is disabled when CALENDAR_INTEGRATION=disabled', () => {
    process.env.CALENDAR_INTEGRATION = 'disabled';
    expect(isCalendarEnabled()).toBe(false);
  });
});
