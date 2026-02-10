import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import { type Meeting, RecordingCollection, type Transcript } from './transcript.dtos';

@Injectable()
export class TranscriptRecordingService {
  private readonly logger = new Logger(TranscriptRecordingService.name);

  public constructor(
    private readonly trace: TraceService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly unique: UniqueService,
  ) {}

  /**
   * Fetch the correlated recording from MS Graph and store it in KB.
   * Recording failures are logged but don't fail the transcript processing.
   */
  @Span()
  public async fetchAndStore(
    userProfileId: string,
    userId: string,
    meetingId: string,
    meeting: Meeting,
    transcript: Transcript,
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('content_correlation_id', transcript.contentCorrelationId);
    span?.setAttribute('meeting_id', meetingId);

    try {
      const client = this.graphClientFactory.createClientForUser(userProfileId);

      // Query recordings filtered by contentCorrelationId
      const recordingsResponse = await client
        .api(`/users/${userId}/onlineMeetings/${meetingId}/recordings`)
        .filter(`contentCorrelationId eq '${transcript.contentCorrelationId}'`)
        .get();

      const recordings = await RecordingCollection.parseAsync(recordingsResponse);

      if (recordings.value.length === 0) {
        span?.addEvent('recording_not_found');
        this.logger.debug(
          { contentCorrelationId: transcript.contentCorrelationId, meetingId },
          'No correlated recording found for this transcript',
        );
        return;
      }

      // biome-ignore lint/style/noNonNullAssertion: checked above
      const recording = recordings.value[0]!;

      span?.setAttribute('recording_id', recording.id);
      this.logger.debug(
        { recordingId: recording.id },
        'Located correlated meeting recording in Microsoft Graph',
      );

      // Fetch recording content (MP4 stream)
      const mp4Stream: ReadableStream<Uint8Array<ArrayBuffer>> = await client
        .api(`/users/${userId}/onlineMeetings/${meetingId}/recordings/${recording.id}/content`)
        .header('Accept', 'video/mp4')
        .getStream();

      span?.addEvent('recording_content_retrieved');

      // Store in KB with SKIP_INGESTION
      await this.unique.storeRecording(
        {
          subject: meeting.subject ?? '',
          startDateTime: transcript.createdDateTime,
          contentCorrelationId: transcript.contentCorrelationId,
          participants: meeting.participants.attendees.map((p) => ({
            id: p.identity.user.id ?? undefined,
            name: p.identity.user.displayName ?? '',
            email: p.upn,
          })),
          owner: {
            id: meeting.participants.organizer.identity.user.id,
            name: meeting.participants.organizer.identity.user.displayName ?? '',
            email: meeting.participants.organizer.upn,
          },
        },
        { id: recording.id, content: mp4Stream },
      );

      span?.addEvent('recording_stored', { recordingId: recording.id });
      this.logger.log({ recordingId: recording.id }, 'Successfully stored recording in KB');
    } catch (error) {
      // Log but don't fail - recording may not be available yet
      span?.addEvent('failed_to_retrieve_recording', {
        error: error instanceof Error ? error.message : String(error),
      });
      this.logger.warn(
        { error: error instanceof Error ? error.message : String(error) },
        'Failed to retrieve or store meeting recording, proceeding without it',
      );
    }
  }
}
