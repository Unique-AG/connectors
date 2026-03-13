import z from 'zod/v4';
import { isoDatetimeToDate, stringToURL } from '../shared/primitives';
import { MeetingOrganizer } from './online-meeting.schema';

/**
 * Represents a recording associated with an online meeting.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/callrecording?view=graph-rest-1.0
 */
export const CallRecording = z.object({
  id: z.string(),
  meetingId: z.string(),
  callId: z.string(),
  contentCorrelationId: z.string(),
  recordingContentUrl: stringToURL(),
  createdDateTime: isoDatetimeToDate({ offset: true }),
  endDateTime: isoDatetimeToDate({ offset: true }),
  meetingOrganizer: MeetingOrganizer,
});

export type CallRecording = z.infer<typeof CallRecording>;
