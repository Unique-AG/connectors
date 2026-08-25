import { describe, expect, it } from 'vitest';
import type { GraphCalendar } from '../../calendar.schemas';
import { mapGraphCalendarToCalendarRef } from '../map-graph-calendar-to-calendar-ref';

const CALLER = 'me@example.com';

function calendar(overrides: Partial<GraphCalendar> & { id: string }): GraphCalendar {
  return {
    name: 'Calendar',
    canEdit: true,
    canViewPrivateItems: true,
    ...overrides,
  };
}

describe(mapGraphCalendarToCalendarRef.name, () => {
  it('marks the caller calendar as ownMailbox', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-own',
        isDefaultCalendar: true,
        isTallyingResponses: true,
        owner: { address: 'ME@example.com', name: 'Me' },
      }),
      callerEmail: CALLER,
    });

    expect(result).toMatchObject({
      calendarId: 'cal-own',
      isOwn: true,
      accessPath: 'ownMailbox',
      ownerEmail: 'ME@example.com',
    });
  });

  it('routes a shared owner-primary calendar to ownerMailbox', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-primary',
        name: 'Banker',
        isDefaultCalendar: false,
        isTallyingResponses: true,
        canShare: false,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
      callerEmail: CALLER,
    });

    expect(result).toMatchObject({
      isOwn: false,
      accessPath: 'ownerMailbox',
      ownerEmail: 'banker@example.com',
    });
  });

  it('routes a shared custom calendar to ownMailbox', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-custom',
        name: 'Projects',
        isDefaultCalendar: false,
        isTallyingResponses: false,
        canShare: false,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
      callerEmail: CALLER,
    });

    expect(result).toMatchObject({
      isOwn: false,
      accessPath: 'ownMailbox',
      ownerEmail: 'banker@example.com',
    });
  });

  it('uses ownMailbox when Graph omits the owner', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({ id: 'cal-unknown', isDefaultCalendar: true }),
      callerEmail: CALLER,
    });

    expect(result).toMatchObject({
      isOwn: false,
      ownerEmail: null,
      accessPath: 'ownMailbox',
    });
  });

  it('forces ownerMailbox when listing from the owner mailbox path', () => {
    const result = mapGraphCalendarToCalendarRef({
      calendar: calendar({
        id: 'cal-owner',
        name: 'Calendar',
        isDefaultCalendar: true,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
      callerEmail: CALLER,
      accessPathOverride: 'ownerMailbox',
    });

    expect(result).toMatchObject({
      isOwn: false,
      accessPath: 'ownerMailbox',
      ownerEmail: 'banker@example.com',
    });
  });
});
