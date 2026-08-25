import { GraphError } from '@microsoft/microsoft-graph-client';
import { Temporal } from 'temporal-polyfill';
import { describe, expect, it, vi } from 'vitest';
import type { ResolvedMailboxTimezone } from '~/features/user-utils/resolve-mailbox-timezone.query';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SuggestMeetingTimesQuery } from '../suggest-meeting-times.query';

const USER_PROFILE_ID = convertUserProfileIdToTypeId('user_profile_01kqcg8m7teh6sh8tehd2k0byb');
const OWN_EMAIL = 'me@example.com';
const ATTENDEE = 'alex@example.com';
const PATH = `/users/${OWN_EMAIL}/findMeetingTimes`;
const PREFER = 'outlook.timezone="W. Europe Standard Time"';
const NOW = Temporal.ZonedDateTime.from('2026-08-25T15:30:00+02:00[Europe/Zurich]');
const DEFAULT_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'Europe/Zurich',
  outlookTimeZone: 'W. Europe Standard Time',
  notes: [],
};
const UNMAPPED_TIMEZONE: ResolvedMailboxTimezone = {
  ianaTimeZone: 'UTC',
  outlookTimeZone: 'UTC',
  notes: [
    'Mailbox timezone "Customized Time Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
  ],
};

function makeGraphError(statusCode: number, code: string): GraphError {
  const err = new GraphError(statusCode, 'Access denied');
  err.code = code;
  return err;
}

function createQuery(
  opts: { post?: ReturnType<typeof vi.fn>; timezone?: ResolvedMailboxTimezone } = {},
) {
  const post = opts.post ?? vi.fn().mockResolvedValue({ meetingTimeSuggestions: [] });
  const request = {
    header: vi.fn().mockReturnThis(),
    post,
  };
  const api = vi.fn().mockReturnValue(request);
  const query = new SuggestMeetingTimesQuery(
    { createClientForUser: vi.fn().mockReturnValue({ api }) } as never,
    {
      run: vi.fn().mockResolvedValue({
        id: USER_PROFILE_ID.toString(),
        email: OWN_EMAIL,
        source: 'oauth',
      }),
    } as never,
    {
      run: vi.fn().mockResolvedValue(opts.timezone ?? DEFAULT_TIMEZONE),
    } as never,
  );
  return { query, api, request, post };
}

describe(SuggestMeetingTimesQuery.name, () => {
  it('POSTs findMeetingTimes on /users/{email} and maps ranked slots', async () => {
    const { query, api, request, post } = createQuery({
      post: vi.fn().mockResolvedValue({
        emptySuggestionsReason: '',
        meetingTimeSuggestions: [
          {
            confidence: 100,
            organizerAvailability: 'free',
            suggestionReason: 'Nearest time when all attendees are available.',
            attendeeAvailability: [
              {
                availability: 'free',
                attendee: { emailAddress: { address: ATTENDEE } },
              },
            ],
            meetingTimeSlot: {
              start: {
                dateTime: '2026-08-26T09:00:00.0000000',
                timeZone: 'W. Europe Standard Time',
              },
              end: { dateTime: '2026-08-26T09:30:00.0000000', timeZone: 'W. Europe Standard Time' },
            },
          },
        ],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'tomorrow',
      durationMinutes: 90,
      now: NOW,
    });

    expect(api).toHaveBeenCalledWith(PATH);
    expect(request.header).toHaveBeenCalledWith('Prefer', PREFER);
    expect(post).toHaveBeenCalledWith({
      attendees: [{ type: 'required', emailAddress: { address: ATTENDEE } }],
      timeConstraint: {
        activityDomain: 'work',
        timeSlots: [
          {
            start: { dateTime: '2026-08-26T00:00:00', timeZone: 'W. Europe Standard Time' },
            end: { dateTime: '2026-08-26T23:59:59', timeZone: 'W. Europe Standard Time' },
          },
        ],
      },
      meetingDuration: 'PT1H30M',
      maxCandidates: 5,
      isOrganizerOptional: false,
      returnSuggestionReasons: true,
      minimumAttendeePercentage: 50,
    });
    expect(result.success).toBe(true);
    expect(result.emptySuggestionsReason).toBeNull();
    expect(result.suggestions).toEqual([
      {
        start: { dateTime: '2026-08-26T09:00:00.0000000', timeZone: 'W. Europe Standard Time' },
        end: { dateTime: '2026-08-26T09:30:00.0000000', timeZone: 'W. Europe Standard Time' },
        confidence: 100,
        organizerAvailability: 'free',
        suggestionReason: 'Nearest time when all attendees are available.',
        attendeeAvailability: [{ email: ATTENDEE, availability: 'free' }],
      },
    ]);
  });

  it('clamps today so suggestions start from now', async () => {
    const { query, post } = createQuery();

    const result = await query.run(USER_PROFILE_ID, {
      range: 'today',
      now: NOW,
    });

    expect(result.success).toBe(true);
    expect(result.suggestionNotes).toEqual([
      'The start of the window was in the past; suggestions start from now.',
    ]);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        timeConstraint: {
          activityDomain: 'work',
          timeSlots: [
            {
              start: { dateTime: '2026-08-25T15:30:00', timeZone: 'W. Europe Standard Time' },
              end: { dateTime: '2026-08-25T23:59:59', timeZone: 'W. Europe Standard Time' },
            },
          ],
        },
      }),
    );
  });

  it('rejects a window that is entirely in the past', async () => {
    const { query, post } = createQuery();

    const result = await query.run(USER_PROFILE_ID, {
      range: 'yesterday',
      now: NOW,
    });

    expect(result.success).toBe(false);
    expect(result.message).toMatch(/past/);
    expect(post).not.toHaveBeenCalled();
  });

  it('sends UTC wall-clock times when the mailbox timezone cannot be mapped', async () => {
    const { query, post } = createQuery({ timezone: UNMAPPED_TIMEZONE });

    const result = await query.run(USER_PROFILE_ID, {
      startDateTime: '2026-08-26T09:00:00+02:00',
      endDateTime: '2026-08-26T18:00:00+02:00',
      now: NOW,
    });

    expect(result.suggestionNotes).toEqual([
      'Mailbox timezone "Customized Time Zone" could not be mapped to IANA; relative windows are resolved in UTC.',
    ]);
    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        timeConstraint: {
          activityDomain: 'work',
          timeSlots: [
            {
              start: { dateTime: '2026-08-26T07:00:00', timeZone: 'UTC' },
              end: { dateTime: '2026-08-26T16:00:00', timeZone: 'UTC' },
            },
          ],
        },
      }),
    );
  });

  it('passes optional findMeetingTimes constraints through to Graph', async () => {
    const { query, post } = createQuery();

    await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'tomorrow',
      maxCandidates: 8,
      activityDomain: 'unrestricted',
      isOrganizerOptional: true,
      minimumAttendeePercentage: 80,
      now: NOW,
    });

    expect(post).toHaveBeenCalledWith(
      expect.objectContaining({
        maxCandidates: 8,
        isOrganizerOptional: true,
        minimumAttendeePercentage: 80,
        timeConstraint: expect.objectContaining({ activityDomain: 'unrestricted' }),
      }),
    );
  });

  it('returns emptySuggestionsReason when Graph finds no slots', async () => {
    const { query } = createQuery({
      post: vi.fn().mockResolvedValue({
        emptySuggestionsReason: 'attendeesUnavailable',
        meetingTimeSuggestions: [],
      }),
    });

    const result = await query.run(USER_PROFILE_ID, {
      attendees: [ATTENDEE],
      range: 'tomorrow',
      now: NOW,
    });

    expect(result.success).toBe(true);
    expect(result.suggestions).toEqual([]);
    expect(result.emptySuggestionsReason).toBe('attendeesUnavailable');
    expect(result.message).toMatch(/attendeesUnavailable/);
    expect(result.suggestionNotes?.[0]).toMatch(/Widen the window/);
  });

  it('returns consentRequired when the caller mailbox is denied', async () => {
    const { query } = createQuery({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      range: 'today',
      now: NOW,
    });

    expect(result.success).toBe(false);
    expect(result.consentRequired).toBe(true);
  });

  it('does not treat a delegated mailbox 403 as missing consent', async () => {
    const { query, api } = createQuery({
      post: vi.fn().mockRejectedValue(makeGraphError(403, 'ErrorAccessDenied')),
    });

    const result = await query.run(USER_PROFILE_ID, {
      mailbox: 'banker@example.com',
      range: 'today',
      now: NOW,
    });

    expect(api).toHaveBeenCalledWith('/users/banker@example.com/findMeetingTimes');
    expect(result.success).toBe(false);
    expect(result.consentRequired).toBeUndefined();
  });
});
