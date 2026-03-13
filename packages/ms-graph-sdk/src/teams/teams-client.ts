import { buildUrl } from '../shared/odata';
import type { GraphPagedResponse } from '../shared/pagination';
import { paginate } from '../shared/pagination';
import { CallRecording } from './call-recording.schema';
import { CallTranscript } from './call-transcript.schema';
import { OnlineMeeting } from './online-meeting.schema';
import type {
  GetCallRecordingContentRequest,
  GetCallTranscriptContentRequest,
  GetCallTranscriptRequest,
  GetOnlineMeetingRequest,
  ListCallRecordingsRequest,
} from './teams.requests';

export class TeamsClient {
  public constructor(private readonly fetch: typeof globalThis.fetch) {}

  /**
   * Retrieve the properties and relationships of an online meeting object.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/onlinemeeting-get?view=graph-rest-1.0
   */
  public async getMeeting(params: GetOnlineMeetingRequest): Promise<OnlineMeeting> {
    const response = await this.fetch(`/users/${params.userId}/onlineMeetings/${params.meetingId}`);
    return OnlineMeeting.parse(await response.json());
  }

  /**
   * Retrieve a callTranscript object associated with a scheduled online meeting.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0
   */
  public async getTranscript(params: GetCallTranscriptRequest): Promise<CallTranscript> {
    const response = await this.fetch(
      `/users/${params.userId}/onlineMeetings/${params.meetingId}/transcripts/${params.transcriptId}`,
    );
    return CallTranscript.parse(await response.json());
  }

  /**
   * Retrieve the content stream of a callTranscript associated with a scheduled online meeting.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/calltranscript-get?view=graph-rest-1.0
   */
  public getTranscriptContent(params: GetCallTranscriptContentRequest): Promise<Response> {
    return this.fetch(
      `/users/${params.userId}/onlineMeetings/${params.meetingId}/transcripts/${params.transcriptId}/content`,
      { headers: { Accept: params.accept } },
    );
  }

  /**
   * Get the list of callRecording objects associated with a scheduled online meeting.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/onlinemeeting-list-recordings?view=graph-rest-1.0
   */
  public listRecordings(params: ListCallRecordingsRequest): GraphPagedResponse<CallRecording> {
    const { userId, meetingId, ...odata } = params;
    const url = buildUrl(`/users/${userId}/onlineMeetings/${meetingId}/recordings`, odata);
    return paginate(this.fetch, url, CallRecording);
  }

  /**
   * Retrieve the content stream of a callRecording associated with a scheduled online meeting.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/callrecording-get?view=graph-rest-1.0
   */
  public getRecordingContent(params: GetCallRecordingContentRequest): Promise<Response> {
    return this.fetch(
      `/users/${params.userId}/onlineMeetings/${params.meetingId}/recordings/${params.recordingId}/content`,
      { headers: { Accept: 'video/mp4' } },
    );
  }
}
