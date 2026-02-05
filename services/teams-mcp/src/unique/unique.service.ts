import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
import type { UniqueConfigNamespaced } from '~/config';
import {
  type PublicScopeAccessSchema,
  ScopeAccessEntityType,
  ScopeAccessType,
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
      participants: { id?: string; name: string; email: string }[];
      owner: { id: string; name: string; email: string };
    },
    transcript: { id: string; content: ReadableStream<Uint8Array<ArrayBuffer>> },
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('transcript_id', transcript.id);
    span?.setAttribute('participant_count', meeting.participants.length);
    span?.setAttribute('meeting_date', meeting.startDateTime.toISOString());
    span?.setAttribute('owner_id', meeting.owner.id);

    this.logger.log(
      {
        transcriptId: transcript.id,
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

    const { parentPath, childPath } = this.mapMeetingToScopePaths(
      meeting.subject,
      meeting.startDateTime,
    );

    const parentScope = await this.scopeService.createScope(parentPath, false);
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

    const childScope = await this.scopeService.createScope(childPath, true);
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
          participant_names: meeting.participants.map((p) => p.name).join(', '),
          participant_emails: meeting.participants.map((p) => p.email).join(', '),
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

    span?.addEvent('ingestion_completed', {
      transcriptId: transcript.id,
      parentScopeId: parentScope.id,
      childScopeId: childScope.id,
    });

    this.logger.log(
      {
        transcriptId: transcript.id,
        parentScopeId: parentScope.id,
        childScopeId: childScope.id,
      },
      'Successfully completed meeting transcript ingestion process',
    );
  }

  private mapMeetingToScopePaths(
    subject: string,
    happenedAt: Date,
  ): { parentPath: string; childPath: string } {
    const rootScopePath = this.config.get('unique.rootScopePath', { infer: true });
    // biome-ignore lint/style/noNonNullAssertion: iso string is always with T
    const formattedDate = happenedAt.toISOString().split('T').at(0)!;
    const meetingSubject = subject || 'Untitled Meeting';
    const parentPath = `/${rootScopePath}/${meetingSubject}`;
    const childPath = `${parentPath}/${formattedDate}`;
    return { parentPath, childPath };
  }
}
