import { describe, expect, it } from 'vitest';
import type { GraphCalendar } from '../calendar.schemas';
import { classifyCalendar } from '../classify-calendar';

const CALLER = 'me@example.com';

function calendar(overrides: Partial<GraphCalendar> & { id: string }): GraphCalendar {
  return {
    name: 'Calendar',
    canEdit: true,
    canViewPrivateItems: true,
    ...overrides,
  };
}

describe(classifyCalendar.name, () => {
  it('marks the caller calendar as ownMailbox', () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-own',
        isDefaultCalendar: true,
        isTallyingResponses: true,
        owner: { address: 'ME@example.com', name: 'Me' },
      }),
      CALLER,
    );

    expect(result).toMatchObject({
      calendarId: 'cal-own',
      isOwn: true,
      accessPath: 'ownMailbox',
      ownerEmail: 'ME@example.com',
    });
  });

  it('routes a shared owner-primary calendar to ownerMailbox', () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-primary',
        name: 'Banker',
        isDefaultCalendar: false,
        isTallyingResponses: true,
        canShare: false,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
      CALLER,
    );

    expect(result).toMatchObject({
      isOwn: false,
      accessPath: 'ownerMailbox',
      ownerEmail: 'banker@example.com',
    });
  });

  it('routes a shared custom calendar to ownMailbox', () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-custom',
        name: 'Projects',
        isDefaultCalendar: false,
        isTallyingResponses: false,
        canShare: false,
        owner: { address: 'banker@example.com', name: 'Banker' },
      }),
      CALLER,
    );

    expect(result).toMatchObject({
      isOwn: false,
      accessPath: 'ownMailbox',
      ownerEmail: 'banker@example.com',
    });
  });

  it('uses ownMailbox when Graph omits the owner', () => {
    const result = classifyCalendar(
      calendar({ id: 'cal-unknown', isDefaultCalendar: true }),
      CALLER,
    );

    expect(result).toMatchObject({
      isOwn: false,
      ownerEmail: null,
      accessPath: 'ownMailbox',
    });
  });
});
