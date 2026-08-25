import { describe, expect, it } from 'vitest';
import type { CalendarRef } from '../calendar.schemas';
import { calendarViewPath } from '../calendar-view-path';

const own: CalendarRef = {
  calendarId: 'cal-1',
  name: 'Calendar',
  ownerEmail: 'me@example.com',
  ownerName: 'Me',
  isOwn: true,
  canEdit: true,
  canViewPrivateItems: true,
  accessPath: 'ownMailbox',
};

const delegated: CalendarRef = {
  calendarId: 'cal-2',
  name: 'Banker',
  ownerEmail: 'banker@example.com',
  ownerName: 'Banker',
  isOwn: false,
  canEdit: true,
  canViewPrivateItems: false,
  accessPath: 'ownerMailbox',
};

describe(calendarViewPath.name, () => {
  it('uses /me/calendars for the caller mailbox', () => {
    expect(calendarViewPath(own, { source: 'oauth', email: 'me@example.com' })).toBe(
      '/me/calendars/cal-1/calendarView',
    );
  });

  it('uses /users/{email}/calendars for a shared-mailbox profile', () => {
    expect(calendarViewPath(own, { source: 'shared-mailbox', email: 'shared@example.com' })).toBe(
      '/users/shared@example.com/calendars/cal-1/calendarView',
    );
  });

  it('uses the owner mailbox path for delegated calendars', () => {
    expect(calendarViewPath(delegated, { source: 'oauth', email: 'me@example.com' })).toBe(
      '/users/banker@example.com/calendars/cal-2/calendarView',
    );
  });
});
