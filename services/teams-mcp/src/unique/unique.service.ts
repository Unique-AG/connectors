import { createHash } from 'node:crypto';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import type { UniqueConfigNamespaced } from '~/config';
import { buildMeetingExternalId, buildOccurrenceExternalId } from './scope-external-id';
import { TEAMS_SOURCE_KIND, TEAMS_SOURCE_NAME } from './unique.consts';
import {
  type PublicScopeAccessSchema,
  ScopeAccessEntityType,
  ScopeAccessType,
  SourceOwnerType,
  UniqueIngestionMode,
} from './unique.dtos';
import { UniqueContentService } from './unique-content.service';
import { UniqueScopeService } from './unique-scope.service';
import { UniqueUserService } from './unique-user.service';

@Injectable()
export class UniqueService {
  private readonly logger = new Logger(UniqueService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly trace: TraceService,
    private readonly userService: UniqueUserService,
    private readonly scopeService: UniqueScopeService,
    private readonly contentService: UniqueContentService,
  ) {}

  @Span()
  public async ingestTranscript(
    meeting: {
      meetingId: string;
      subject: string;
      date: Date;
      startDateTime: Date;
      endDateTime: Date;
      contentCorrelationId: string;
      participants: { id?: string; name: string; email: string }[];
      owner: { id: string; name: string; email: string };
    },
    transcript: {
      id: string;
      content: () => Promise<Response>;
    },
    recording?: {
      id: string;
      content: () => Promise<Response>;
      startDateTime: Date;
      endDateTime: Date;
    },
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('transcript_id', transcript.id);
    span?.setAttribute('participant_count', meeting.participants.length);
    span?.setAttribute('meeting_date', meeting.date.toISOString());
    span?.setAttribute('owner_id', meeting.owner.id);
    if (recording) {
      span?.setAttribute('recording_id', recording.id);
    }

    this.logger.log(
      {
        transcriptId: transcript.id,
        recordingId: recording?.id,
        participantCount: meeting.participants.length,
        meetingDate: meeting.date.toISOString(),
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
      meeting.meetingId,
      meeting.date,
    );

    const parentScope = await this.scopeService.createScope(rootScopeId, subjectPath, false);
    span?.setAttribute('parent_scope_id', parentScope.id);

    // Stamp the meeting (subject) scope with a deterministic externalId so it is
    // externally managed (locked in the UI) and idempotently re-stampable.
    await this.scopeService.updateScope(parentScope.id, {
      externalId: buildMeetingExternalId(meeting.meetingId),
    });

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

    // Stamp the occurrence (session) scope, anchored on the transcript id so each
    // recording session gets a unique externalId even for same-day meetings.
    await this.scopeService.updateScope(childScope.id, {
      externalId: buildOccurrenceExternalId(meeting.meetingId, transcript.id),
    });

    this.logger.log(
      { transcriptId: transcript.id, scopeId: childScope.id },
      'Beginning transcript upload to Unique system',
    );

    const transcriptUpload = await this.contentService.upsertContent({
      storeInternally: true,
      scopeId: childScope.id,
      sourceKind: TEAMS_SOURCE_KIND,
      sourceName: TEAMS_SOURCE_NAME,
      sourceOwnerType: SourceOwnerType.Company,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: meeting.subject || 'Untitled Meeting',
        byteSize: 1,
        metadata: this.buildContentMetadata(meeting),
      },
    });

    await this.contentService.uploadToStorage(
      transcriptUpload.writeUrl,
      transcript.content,
      'text/vtt',
    );

    await this.contentService.upsertContent({
      storeInternally: true,
      scopeId: childScope.id,
      sourceKind: TEAMS_SOURCE_KIND,
      sourceName: TEAMS_SOURCE_NAME,
      sourceOwnerType: SourceOwnerType.Company,
      fileUrl: transcriptUpload.readUrl,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: meeting.subject || 'Untitled Meeting',
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
          sourceKind: TEAMS_SOURCE_KIND,
          sourceName: TEAMS_SOURCE_NAME,
          sourceOwnerType: SourceOwnerType.Company,
          input: {
            key: recording.id,
            mimeType: 'video/mp4',
            title: meeting.subject || 'Untitled Meeting',
            byteSize: 1,
            ingestionConfig: {
              uniqueIngestionMode: UniqueIngestionMode.SKIP_INGESTION,
            },
            metadata: this.buildContentMetadata(meeting, recording),
          },
        });
        await this.contentService.uploadToStorage(
          recordingUpload.writeUrl,
          recording.content,
          'video/mp4',
        );
        await this.contentService.upsertContent({
          storeInternally: true,
          scopeId: childScope.id,
          sourceKind: TEAMS_SOURCE_KIND,
          sourceName: TEAMS_SOURCE_NAME,
          sourceOwnerType: SourceOwnerType.Company,
          fileUrl: recordingUpload.readUrl,
          input: {
            key: recording.id,
            mimeType: 'video/mp4',
            title: meeting.subject || 'Untitled Meeting',
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
    meetingId: string,
    happenedAt: Date,
  ): { subjectPath: string; datePath: string } {
    // Parent (subject) folder: human-readable subject plus a stable, path-safe
    // suffix derived from the meetingId. Recurring occurrences of one series
    // share the same meetingId (and subject) so they collapse into one folder
    // as intended; two *different* meetings that happen to share a title get
    // distinct folders, so their `meeting` externalIds no longer overwrite each
    // other. e.g. "Weekly Sync (a1b2c3d4)"
    const subjectPath = `${subject || 'Untitled Meeting'} (${this.shortHash(meetingId)})`;

    // Child (session) folder: second-precision UTC timestamp (not just the
    // calendar date) so multiple transcripts/recordings on the same day each
    // get their own folder. `happenedAt` is the transcript's createdDateTime —
    // the onlineMeeting startDateTime is the recurring series' master time and
    // is identical for every occurrence, so it cannot be used here. ':' -> '-'
    // keeps the segment path-safe (the folder API splits on '/'). e.g.
    // "2024-01-15 14-30-45"
    const datePath = happenedAt.toISOString().slice(0, 19).replace('T', ' ').replaceAll(':', '-');

    return { subjectPath, datePath };
  }

  /**
   * Short, stable, path-safe digest of an id — used to disambiguate folder
   * names without leaking the raw Graph id (which can contain '/', '+', '='
   * that would break folder paths). Deterministic, so re-ingestion re-uses the
   * same folder.
   */
  private shortHash(value: string): string {
    return createHash('sha256').update(value).digest('hex').slice(0, 8);
  }

  private buildContentMetadata(
    meeting: {
      date: Date;
      startDateTime: Date;
      endDateTime: Date;
      contentCorrelationId: string;
      owner: { name: string; email: string };
      participants: { name: string; email: string }[];
    },
    datetimeOverride?: { startDateTime: Date; endDateTime: Date },
  ): Record<string, string> {
    const startDateTime = datetimeOverride?.startDateTime ?? meeting.startDateTime;
    const endDateTime = datetimeOverride?.endDateTime ?? meeting.endDateTime;
    const metadata: Record<string, string> = {
      date: meeting.date.toISOString(),
      start_datetime: startDateTime.toISOString(),
      end_datetime: endDateTime.toISOString(),
      content_correlation_id: meeting.contentCorrelationId,
      organizer_email: meeting.owner.email.toLowerCase(),
    };

    if (meeting.owner.name) {
      metadata.organizer_name = meeting.owner.name;
    }

    // Filter out empty names/emails before joining
    const names = meeting.participants.map((p) => p.name).filter(Boolean);
    const emails = meeting.participants.map((p) => p.email).filter(Boolean);

    if (names.length > 0) {
      metadata.participant_names = names.join(', ');
    }
    if (emails.length > 0) {
      metadata.participant_emails = emails.join(', ');
    }

    return metadata;
  }
}
