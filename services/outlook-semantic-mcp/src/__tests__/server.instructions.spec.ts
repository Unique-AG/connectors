import { afterEach, describe, expect, it } from 'vitest';
import { buildServerInstructions } from '../server.instructions';

describe(buildServerInstructions.name, () => {
  const original = process.env.CALENDAR_INTEGRATION;

  afterEach(() => {
    if (original === undefined) {
      delete process.env.CALENDAR_INTEGRATION;
    } else {
      process.env.CALENDAR_INTEGRATION = original;
    }
  });

  it('omits calendar instructions when CALENDAR_INTEGRATION is disabled', () => {
    process.env.CALENDAR_INTEGRATION = 'disabled';
    expect(buildServerInstructions()).not.toContain('list_calendars');
    expect(buildServerInstructions()).not.toContain('search_calendar_events');
    expect(buildServerInstructions()).not.toContain('check_availability');
    expect(buildServerInstructions()).not.toContain('suggest_meeting_times');
    expect(buildServerInstructions()).not.toContain('respond_to_invite');
    expect(buildServerInstructions()).not.toContain('create_event');
  });

  it('includes calendar instructions when CALENDAR_INTEGRATION is enabled', () => {
    process.env.CALENDAR_INTEGRATION = 'enabled';
    expect(buildServerInstructions()).toContain('list_calendars');
    expect(buildServerInstructions()).toContain('search_calendar_events');
    expect(buildServerInstructions()).toContain('check_availability');
    expect(buildServerInstructions()).toContain('suggest_meeting_times');
    expect(buildServerInstructions()).toContain('respond_to_invite');
    expect(buildServerInstructions()).toContain('create_event');
  });
});
