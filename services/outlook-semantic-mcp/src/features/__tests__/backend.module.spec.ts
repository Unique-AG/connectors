import { afterEach, describe, expect, it } from 'vitest';
import { registerBackendModule } from '../backend.module';
import { CalendarModule } from '../calendar/calendar.module';
import { ListCalendarsTool } from '../calendar/list-calendars.tool';

describe(registerBackendModule.name, () => {
  const original = process.env.CALENDAR_INTEGRATION;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.CALENDAR_INTEGRATION;
    } else {
      process.env.CALENDAR_INTEGRATION = original;
    }
  });

  it('omits calendar tools when CALENDAR_INTEGRATION is disabled', () => {
    process.env.CALENDAR_INTEGRATION = 'disabled';
    const module = registerBackendModule();

    expect(module.imports).not.toContain(CalendarModule);
    expect(module.providers).not.toContain(ListCalendarsTool);
  });

  it('registers calendar tools when CALENDAR_INTEGRATION is enabled', () => {
    process.env.CALENDAR_INTEGRATION = 'enabled';
    const module = registerBackendModule();

    expect(module.imports).toContain(CalendarModule);
    expect(module.providers).toContain(ListCalendarsTool);
  });
});
