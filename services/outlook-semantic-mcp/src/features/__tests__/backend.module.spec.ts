import { afterEach, describe, expect, it } from 'vitest';
import { registerBackendModule } from '../backend.module';
import { CalendarModule } from '../calendar/calendar.module';
import { CancelEventTool } from '../calendar/cancel-event.tool';
import { CheckAvailabilityTool } from '../calendar/check-availability.tool';
import { CreateEventTool } from '../calendar/create-event.tool';
import { ListCalendarsTool } from '../calendar/list-calendars.tool';
import { RespondToInviteTool } from '../calendar/respond-to-invite.tool';
import { SearchCalendarEventsTool } from '../calendar/search-calendar-events.tool';
import { SuggestMeetingTimesTool } from '../calendar/suggest-meeting-times.tool';
import { UpdateEventTool } from '../calendar/update-event.tool';

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
    expect(module.providers).not.toContain(SearchCalendarEventsTool);
    expect(module.providers).not.toContain(CheckAvailabilityTool);
    expect(module.providers).not.toContain(SuggestMeetingTimesTool);
    expect(module.providers).not.toContain(RespondToInviteTool);
    expect(module.providers).not.toContain(CreateEventTool);
    expect(module.providers).not.toContain(UpdateEventTool);
    expect(module.providers).not.toContain(CancelEventTool);
  });

  it('registers calendar tools when CALENDAR_INTEGRATION is enabled', () => {
    process.env.CALENDAR_INTEGRATION = 'enabled';
    const module = registerBackendModule();

    expect(module.imports).toContain(CalendarModule);
    expect(module.providers).toContain(ListCalendarsTool);
    expect(module.providers).toContain(SearchCalendarEventsTool);
    expect(module.providers).toContain(CheckAvailabilityTool);
    expect(module.providers).toContain(SuggestMeetingTimesTool);
    expect(module.providers).toContain(RespondToInviteTool);
    expect(module.providers).toContain(CreateEventTool);
    expect(module.providers).toContain(UpdateEventTool);
    expect(module.providers).toContain(CancelEventTool);
  });
});
