import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import type { UniqueConfigNamespaced } from '~/config';
import {
  type PublicScopeAccessSchema,
  ScopeAccessEntityType,
  ScopeAccessType,
  UniqueIngestionMode,
} from './unique.dtos';
import { UniqueApiClient } from './unique-api.client';
import { UniqueContentService } from './unique-content.service';
import { UniqueScopeService } from './unique-scope.service';
import { UniqueUserService } from './unique-user.service';

@Injectable()
export class UniqueService {
  private readonly logger = new Logger(UniqueService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly trace: TraceService,
    private readonly api: UniqueApiClient,
    private readonly userService: UniqueUserService,
    private readonly scopeService: UniqueScopeService,
    private readonly contentService: UniqueContentService,
  ) {}

  @Span()
  public async ingestTranscript(
    meeting: {
      subject: string;
      startDateTime: Date;
      endDateTime: Date;
      contentCorrelationId: string;
      participants: { id?: string; name: string; email: string }[];
      owner: { id: string; name: string; email: string };
    },
    transcript: { id: string; content: ReadableStream<Uint8Array<ArrayBuffer>> },
    recording?: { id: string; content: ReadableStream<Uint8Array<ArrayBuffer>> },
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('transcript_id', transcript.id);
    span?.setAttribute('participant_count', meeting.participants.length);
    span?.setAttribute('meeting_date', meeting.startDateTime.toISOString());
    span?.setAttribute('owner_id', meeting.owner.id);
    if (recording) {
      span?.setAttribute('recording_id', recording.id);
    }

    this.logger.log(
      {
        transcriptId: transcript.id,
        recordingId: recording?.id,
        participantCount: meeting.participants.length,
        meetingDate: meeting.startDateTime.toISOString(),
      },
      'Beginning processing of meeting transcript for ingestion',
    );

    const concurrency = this.config.get('unique.userFetchConcurrency', { infer: true });
    const limit = pLimit(concurrency);
    const participantsPromises = meeting.participants.map((p) =>
      limit(() => this.userService.findUserByEmail(p.email)),
    );
    const participants = (await Promise.all(participantsPromises)).filter((v) => v !== null);
    const owner = await this.userService.findUserByEmail(meeting.owner.email);

    if (!owner) {
      span?.addEvent('owner_not_found');
      this.logger.warn(
        { participantCount: meeting.participants.length },
        'Cannot proceed: meeting owner account not found in Unique system',
      );
      return;
    }

    span?.setAttribute('resolved_participants_count', participants.length);
    span?.addEvent('participants_resolved', {
      foundParticipants: participants.length,
      totalParticipants: meeting.participants.length,
    });

    this.logger.debug(
      { foundParticipants: participants.length, totalParticipants: meeting.participants.length },
      'Successfully resolved meeting participant accounts in Unique system',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });
    const { subjectPath, datePath } = this.mapMeetingToRelativePaths(
      meeting.subject,
      meeting.startDateTime,
    );

    const parentScope = await this.scopeService.createScope(rootScopeId, subjectPath, false);
    span?.setAttribute('parent_scope_id', parentScope.id);

    const accesses = participants.map<PublicScopeAccessSchema>((p) => ({
      entityId: p.id,
      entityType: ScopeAccessEntityType.User,
      type: ScopeAccessType.Read,
    }));
    accesses.push({
      entityId: owner.id,
      entityType: ScopeAccessEntityType.User,
      type: ScopeAccessType.Write,
    });
    accesses.push({
      entityId: owner.id,
      entityType: ScopeAccessEntityType.User,
      type: ScopeAccessType.Read,
    });
    accesses.push({
      entityId: owner.id,
      entityType: ScopeAccessEntityType.User,
      type: ScopeAccessType.Manage,
    });
    await this.scopeService.addScopeAccesses(parentScope.id, accesses);

    const childScope = await this.scopeService.createScope(parentScope.id, datePath, true);
    span?.setAttribute('child_scope_id', childScope.id);

    this.logger.log(
      { transcriptId: transcript.id, scopeId: childScope.id },
      'Beginning transcript upload to Unique system',
    );

    const transcriptUpload = await this.contentService.upsertContent({
      storeInternally: true,
      scopeId: childScope.id,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: `${meeting.subject}.vtt`,
        byteSize: 1,
        metadata: {
          date: meeting.startDateTime.toISOString(),
          content_correlation_id: meeting.contentCorrelationId,
          participant_names: meeting.participants.map((p) => p.name).join(', '),
          participant_emails: meeting.participants.map((p) => p.email).join(', '),
          // Store participant IDs for permission filtering during search
          participant_user_profile_ids: [...participants.map((p) => p.id), owner.id].join(','),
        },
      },
    });

    const correctedWriteUrl = this.api.correctWriteUrl(transcriptUpload.writeUrl);
    await this.contentService.uploadToStorage(correctedWriteUrl, transcript.content, 'text/vtt');

    await this.contentService.upsertContent({
      storeInternally: true,
      scopeId: childScope.id,
      fileUrl: transcriptUpload.readUrl,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: `${meeting.subject}.vtt`,
      },
    });

    span?.addEvent('transcript_ingestion_completed', {
      transcriptId: transcript.id,
      parentScopeId: parentScope.id,
      childScopeId: childScope.id,
    });

    // Upload recording if provided (with SKIP_INGESTION)
    // Wrapped in try-catch to ensure recording upload failures don't break transcript ingestion
    if (recording) {
      try {
        this.logger.log(
          { recordingId: recording.id, scopeId: childScope.id },
          'Beginning recording upload to Unique system (skip ingestion)',
        );

        const recordingUpload = await this.contentService.upsertContent({
          storeInternally: true,
          scopeId: childScope.id,
          input: {
            key: recording.id,
            mimeType: 'video/mp4',
            title: `${meeting.subject}.mp4`,
            byteSize: 1,
            ingestionConfig: {
              uniqueIngestionMode: UniqueIngestionMode.SKIP_INGESTION,
            },
            metadata: {
              date: meeting.startDateTime.toISOString(),
              content_correlation_id: meeting.contentCorrelationId,
              participant_names: meeting.participants.map((p) => p.name).join(', '),
              participant_emails: meeting.participants.map((p) => p.email).join(', '),
              // Store participant IDs for permission filtering during search
              participant_user_profile_ids: [...participants.map((p) => p.id), owner.id].join(','),
            },
          },
        });
        const correctedRecordingWriteUrl = this.api.correctWriteUrl(recordingUpload.writeUrl);
        await this.contentService.uploadToStorage(
          correctedRecordingWriteUrl,
          recording.content,
          'video/mp4',
        );
        await this.contentService.upsertContent({
          storeInternally: true,
          scopeId: childScope.id,
          fileUrl: recordingUpload.readUrl,
          input: {
            key: recording.id,
            mimeType: 'video/mp4',
            title: `${meeting.subject}.mp4`,
            ingestionConfig: {
              uniqueIngestionMode: UniqueIngestionMode.SKIP_INGESTION,
            },
          },
        });

        span?.addEvent('recording_stored', {
          recordingId: recording.id,
          parentScopeId: parentScope.id,
          childScopeId: childScope.id,
        });
      } catch (error) {
        span?.addEvent('recording_upload_failed', {
          recordingId: recording.id,
          error: error instanceof Error ? error.message : String(error),
        });
        this.logger.warn(
          { error, recordingId: recording.id },
          'Failed to upload recording, transcript ingestion will continue',
        );
      }
    }

    this.logger.log(
      {
        transcriptId: transcript.id,
        recordingId: recording?.id,
        parentScopeId: parentScope.id,
        childScopeId: childScope.id,
      },
      'Successfully completed meeting transcript ingestion process',
    );
  }

  private mapMeetingToRelativePaths(
    subject: string,
    happenedAt: Date,
  ): { subjectPath: string; datePath: string } {
    // biome-ignore lint/style/noNonNullAssertion: iso string is always with T
    const formattedDate = happenedAt.toISOString().split('T').at(0)!;
    const subjectPath = subject || 'Untitled Meeting';
    return { subjectPath, datePath: formattedDate };
  }
}
