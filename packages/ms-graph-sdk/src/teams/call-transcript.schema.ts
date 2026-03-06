import z from 'zod/v4';
import { isoDatetimeToDate, stringToURL } from '../shared/primitives';
import { MeetingOrganizer } from './online-meeting.schema';

/**
 * Represents a transcript associated with an online meeting.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/calltranscript?view=graph-rest-1.0
 */
export const CallTranscript = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  transcriptContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: MeetingOrganizer,
});

export type CallTranscript = z.infer<typeof CallTranscript>;
