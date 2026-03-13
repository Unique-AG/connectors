import z from 'zod/v4';
import { ODataQueryParamsSchema } from '../shared/odata';

/**
 * Parameters for retrieving a specific online meeting.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get?view=graph-rest-1.0
 */
const GetOnlineMeetingRequest = z.object({
  userId: z.string(),
  meetingId: z.string(),
});
export type GetOnlineMeetingRequest = z.infer<typeof GetOnlineMeetingRequest>;

/**
 * Parameters for retrieving a specific call transcript's metadata.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0
 */
const GetCallTranscriptRequest = z.object({
  userId: z.string(),
  meetingId: z.string(),
  transcriptId: z.string(),
});
export type GetCallTranscriptRequest = z.infer<typeof GetCallTranscriptRequest>;

/**
 * Parameters for retrieving the content stream of a call transcript.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0
 */
const GetCallTranscriptContentRequest = z.object({
  userId: z.string(),
  meetingId: z.string(),
  transcriptId: z.string(),
  accept: z.enum(['text/vtt', 'text/plain']).default('text/vtt'),
});
export type GetCallTranscriptContentRequest = z.infer<typeof GetCallTranscriptContentRequest>;

/**
 * Parameters for listing call recordings associated with an online meeting.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-recordings?view=graph-rest-1.0
 */
const ListCallRecordingsRequest = ODataQueryParamsSchema.extend({
  userId: z.string(),
  meetingId: z.string(),
});
export type ListCallRecordingsRequest = z.input<typeof ListCallRecordingsRequest>;

/**
 * Parameters for retrieving the content stream of a call recording.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/callrecording-get?view=graph-rest-1.0
 */
const GetCallRecordingContentRequest = z.object({
  userId: z.string(),
  meetingId: z.string(),
  recordingId: z.string(),
});
export type GetCallRecordingContentRequest = z.infer<typeof GetCallRecordingContentRequest>;
