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
  it("marks the caller's calendar as ownMailbox", () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-own',
        name: 'Calendar',
        isDefaultCalendar: true,
        owner: { address: 'me@example.com', name: 'Me' },
      }),
      CALLER,
    );

    expect(result).toMatchObject({
      calendarId: 'cal-own',
      isOwn: true,
      accessPath: 'ownMailbox',
      ownerEmail: 'me@example.com',
    });
  });

  it('routes a shared primary calendar to ownerMailbox', () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-primary',
        name: 'Banker',
        isDefaultCalendar: true,
        canEdit: true,
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

  it('treats owner email comparison as case-insensitive', () => {
    const result = classifyCalendar(
      calendar({
        id: 'cal-own',
        owner: { address: 'ME@example.com' },
      }),
      CALLER,
    );

    expect(result.isOwn).toBe(true);
    expect(result.accessPath).toBe('ownMailbox');
  });
});
