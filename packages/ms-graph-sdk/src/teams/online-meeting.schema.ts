import z from 'zod/v4';
import { isoDatetimeToDate, stringToURL } from '../shared/primitives';

const MeetingParticipantInfo = z.object({
  upn: z.string(),
  identity: z.object({
    user: z.object({
      id: z.string().nullish(),
      tenantId: z.string().nullish(),
      displayName: z.string().nullish(),
    }),
  }),
});

export type MeetingParticipantInfo = z.infer<typeof MeetingParticipantInfo>;

/**
 * Represents the organizer of an online meeting, using the identitySet resource type.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/identityset?view=graph-rest-1.0
 */
export const MeetingOrganizer = z.object({
  application: z.string().nullable(),
  device: z.string().nullable(),
  user: z.object({
    userIdentityType: z.string(),
    tenantId: z.string(),
    id: z.string(),
    displayName: z.string().nullable(),
  }),
});

export type MeetingOrganizer = z.infer<typeof MeetingOrganizer>;

/**
 * Contains information about a meeting, including the URL used to join a meeting,
 * the attendees list, and the description.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/onlinemeeting?view=graph-rest-1.0
 */
export const OnlineMeeting = z.object({
  id: z.string(),
  subject: z.string().nullish(),
  startDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  joinWebUrl: stringToURL(),
  recordAutomatically: z.boolean().nullish(),
  allowTranscription: z.boolean().nullish(),
  allowRecording: z.boolean().nullish(),
  participants: z.object({
    organizer: MeetingParticipantInfo,
    attendees: z.array(MeetingParticipantInfo),
  }),
});

export type OnlineMeeting = z.infer<typeof OnlineMeeting>;
