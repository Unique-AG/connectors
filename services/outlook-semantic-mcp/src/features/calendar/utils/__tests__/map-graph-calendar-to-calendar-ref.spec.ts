import { describe, expect, it } from 'vitest';
import type { GraphCalendar } from '../../calendar.schemas';
import { mapGraphCalendarToCalendarRef } from '../map-graph-calendar-to-calendar-ref';

const CALLER = 'me@example.com';
const OWNER = 'banker@example.com';

function calendar(overrides: Partial<GraphCalendar> & { id: string }): GraphCalendar {
  return {
    name: 'Calendar',
    canEdit: true,
    canViewPrivateItems: true,
    ...overrides,
  };
}

describe(mapGraphCalendarToCalendarRef.name, () => {
  it('takes the mailbox from the list it was fetched from, not from the owner', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-own',
        isDefaultCalendar: true,
        isTallyingResponses: true,
        owner: { address: 'ME@example.com', name: 'Me' },
      }),
      callerEmail: CALLER,
      mailboxEmail: CALLER,
    });

    expect(result).toMatchObject({
      calendarId: 'cal-own',
      mailbox: CALLER,
      isOwn: true,
      ownerEmail: 'ME@example.com',
    });
  });

  it("keeps a shared calendar in the caller mailbox even when it looks like the owner's primary", () => {
    // Live Graph rejects the caller-namespace id under the owner mailbox with 404
    // ErrorItemNotFound, so isTallyingResponses must not move the calendar to the owner.
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-shared-primary',
        name: 'Banker',
        isDefaultCalendar: false,
        isTallyingResponses: true,
        canShare: false,
        owner: { address: OWNER, name: 'Banker' },
      }),
      callerEmail: CALLER,
      mailboxEmail: CALLER,
    });

    expect(result).toMatchObject({
      mailbox: CALLER,
      isOwn: false,
      ownerEmail: OWNER,
    });
  });

  it('keeps a shared custom calendar in the caller mailbox', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-custom',
        name: 'Projects',
        isDefaultCalendar: false,
        isTallyingResponses: false,
        owner: { address: OWNER, name: 'Banker' },
      }),
      callerEmail: CALLER,
      mailboxEmail: CALLER,
    });

    expect(result).toMatchObject({ mailbox: CALLER, isOwn: false, ownerEmail: OWNER });
  });

  it('uses the owner mailbox when the calendar was listed from the owner mailbox', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-owner',
        name: 'Calendar',
        isDefaultCalendar: true,
        owner: { address: OWNER, name: 'Banker' },
      }),
      callerEmail: CALLER,
      mailboxEmail: OWNER,
    });

    expect(result).toMatchObject({ mailbox: OWNER, isOwn: false, ownerEmail: OWNER });
  });

  it('is not own when Graph omits the owner', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({ id: 'cal-unknown', isDefaultCalendar: true }),
      callerEmail: CALLER,
      mailboxEmail: CALLER,
    });

    expect(result).toMatchObject({ mailbox: CALLER, isOwn: false, ownerEmail: null });
  });
});
