import z from 'zod/v4';
import { isoDatetimeToDate, stringToURL } from '../shared/primitives';

export const MeetingParticipantInfo = z.object({
  upn: z.string(),
  identity: z.object({
    user: z.object({
      id: z.string().nullish(),
      tenantId: z.string().nullish(),
      displayName: z.string().nullish(),
    }),
  }),
});

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

const MeetingOrganizer = z.object({
  application: z.string().nullable(),
  device: z.string().nullable(),
  user: z.object({
    userIdentityType: z.string(),
    tenantId: z.string(),
    id: z.string(),
    displayName: z.string().nullable(),
  }),
});

export const Transcript = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  transcriptContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: MeetingOrganizer,
});

export const Recording = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  recordingContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: MeetingOrganizer,
});

export type OnlineMeeting = z.infer<typeof OnlineMeeting>;
export type Transcript = z.infer<typeof Transcript>;
export type Recording = z.infer<typeof Recording>;
