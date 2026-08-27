import { describe, expect, it } from 'vitest';
import type { GraphCalendar } from '../../calendar.schemas';
import { mapGraphCalendarToCalendarRef } from '../map-graph-calendar-to-calendar-ref';

const USER_PROFILE = 'me@example.com';
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
  it('marks the calendar own when the owner is the signed-in user', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-own',
        isDefaultCalendar: true,
        isTallyingResponses: true,
        owner: { address: 'ME@example.com', name: 'Me' },
      }),
      userProfileEmail: USER_PROFILE,
    });

    expect(result).toMatchObject({
      calendarId: 'cal-own',
      isOwn: true,
      isDefaultCalendar: true,
      ownerEmail: 'ME@example.com',
    });
  });

  it("marks a shared calendar not own even when it looks like the owner's primary", () => {
    // isTallyingResponses is true on a shared primary, but the calendar is still not the caller's.
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-shared-primary',
        name: 'Banker',
        isDefaultCalendar: false,
        isTallyingResponses: true,
        canShare: false,
        owner: { address: OWNER, name: 'Banker' },
      }),
      userProfileEmail: USER_PROFILE,
    });

    expect(result).toMatchObject({
      isOwn: false,
      isDefaultCalendar: false,
      ownerEmail: OWNER,
    });
  });

  it('marks a shared custom calendar not own', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-custom',
        name: 'Projects',
        isDefaultCalendar: false,
        isTallyingResponses: false,
        owner: { address: OWNER, name: 'Banker' },
      }),
      userProfileEmail: USER_PROFILE,
    });

    expect(result).toMatchObject({ isOwn: false, ownerEmail: OWNER });
  });

  it('is not own when Graph omits the owner', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({ id: 'cal-unknown', isDefaultCalendar: true }),
      userProfileEmail: USER_PROFILE,
    });

    expect(result).toMatchObject({
      isOwn: false,
      isDefaultCalendar: true,
      ownerEmail: null,
    });
  });

  it('is not own when Graph returns a null owner', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({ id: 'cal-null-owner', owner: null, isDefaultCalendar: false }),
      userProfileEmail: USER_PROFILE,
    });

    expect(result).toMatchObject({
      isOwn: false,
      ownerEmail: null,
      ownerName: null,
    });
  });
});
