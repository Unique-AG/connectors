import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import {
  PublicAddScopeAccessRequestSchema,
  type PublicAddScopeAccessResult,
  PublicAddScopeAccessResultSchema,
  type PublicContentUpsertRequest,
  PublicContentUpsertRequestSchema,
  type PublicContentUpsertResult,
  PublicContentUpsertResultSchema,
  PublicCreateScopeRequestSchema,
  PublicCreateScopeResultSchema,
  PublicGetUsersRequestSchema,
  type PublicScopeAccessSchema,
  type PublicUserResult,
  PublicUsersResultSchema,
  type Scope,
  ScopeAccessEntityType,
  ScopeAccessType,
  UniqueIngestionMode,
} from './unique.dtos';

@Injectable()
export class UniqueService {
  private readonly logger = new Logger(UniqueService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  private mapMeetingToScope(subject: string, happenedAt: Date, recurring = false): string {
    const rootScopePath = this.config.get('unique.rootScopePath', { infer: true });
    // biome-ignore lint/style/noNonNullAssertion: iso string is always with T
    const formattedDate = happenedAt.toISOString().split('T').at(0)!;
    // TODO: remove any non-alpha numeric characters from subject
    return recurring ? `/${rootScopePath}/${subject}/${formattedDate}` : `/${rootScopePath}/${subject} - ${formattedDate}`;
  }

  private async fetchUserForScopeAccess(email: string): Promise<PublicUserResult | null> {
    const payload = PublicGetUsersRequestSchema.encode({ email });
    const endpoint = new URL('users', this.config.get('unique.apiBaseUrl', { infer: true }));
    // Build query params from payload
    const params = new URLSearchParams();
    Object.entries(payload).forEach(([key, value]) => {
        params.append(key, String(value));
    });

    // Append to endpoint
    const qs = params.toString();
    if (qs) {
      endpoint.search = qs;
    }

    this.logger.debug({ qs, endpoint }, 'calling')

    const response = await fetch(endpoint, {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${this.config.get('unique.appKey', { infer: true }).value}`,
        'x-app-id': this.config.get('unique.appId', { infer: true }),
        'x-api-version': this.config.get('unique.apiVersion', { infer: true }),
        'x-company-id': this.config.get('unique.authCompanyId', { infer: true }),
        'x-user-id': this.config.get('unique.authUserId', { infer: true }),
      },
    });

    if (!response.ok) {
      this.logger.error({ status: response.status, body: await response.text() }, 'Unique Public API return an error');
      throw new Error('Unique Public API return an error ');
    }
    const body = await response.json();
    const result = PublicUsersResultSchema.parse(body);

    return result.users.at(0) ?? null;
  }

  private async createScope(path: string): Promise<Scope> {
    const payload = PublicCreateScopeRequestSchema.encode({ paths: [path] });
    const endpoint = new URL('folder', this.config.get('unique.apiBaseUrl', { infer: true }));

    this.logger.debug({ payload, endpoint: endpoint.toString() }, 'calling create scope ')

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.config.get('unique.appKey', { infer: true }).value}`,
        'x-app-id': this.config.get('unique.appId', { infer: true }),
        'x-api-version': this.config.get('unique.apiVersion', { infer: true }),
        'x-company-id': this.config.get('unique.authCompanyId', { infer: true }),
        'x-user-id': this.config.get('unique.authUserId', { infer: true }),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error({ status: response.status, body: await response.text() }, 'Unique Public API return an error');
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    this.logger.debug({ body }, 'scopes created');
    const result = PublicCreateScopeResultSchema.refine(
      (s) => s.createdFolders.length > 0,
      'no scopes were created',
    ).parse(body);

    // biome-ignore lint/style/noNonNullAssertion: we assert with zod above
    return result.createdFolders[0]!;
  }

  private async addScopeAccesses(
    scope: string,
    accesses: PublicScopeAccessSchema[],
  ): Promise<PublicAddScopeAccessResult> {
    const payload = PublicAddScopeAccessRequestSchema.encode({
      applyToSubScopes: false,
      scopeId: scope,
      scopeAccesses: accesses,
    });
    const endpoint = new URL(
      'folder/add-access',
      this.config.get('unique.apiBaseUrl', { infer: true }),
    );
    const response = await fetch(endpoint, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.config.get('unique.appKey', { infer: true }).value}`,
        'x-app-id': this.config.get('unique.appId', { infer: true }),
        'x-api-version': this.config.get('unique.apiVersion', { infer: true }),
        'x-company-id': this.config.get('unique.authCompanyId', { infer: true }),
        'x-user-id': this.config.get('unique.authUserId', { infer: true }),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error({ status: response.status, body: await response.text() }, 'Unique Public API return an error');
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    const result = PublicAddScopeAccessResultSchema.parse(body);

    return result;
  }

  private async upsertContent(
    content: PublicContentUpsertRequest,
  ): Promise<PublicContentUpsertResult> {
    const payload = PublicContentUpsertRequestSchema.encode(content);
    const endpoint = new URL(
      'content/upsert',
      this.config.get('unique.apiBaseUrl', { infer: true }),
    );
    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${this.config.get('unique.appKey', { infer: true }).value}`,
        'x-app-id': this.config.get('unique.appId', { infer: true }),
        'x-api-version': this.config.get('unique.apiVersion', { infer: true }),
        'x-company-id': this.config.get('unique.authCompanyId', { infer: true }),
        'x-user-id': this.config.get('unique.authUserId', { infer: true }),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error({ status: response.status, body: await response.text() }, 'Unique Public API return an error');
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    this.logger.debug({ body }, 'upsert content')
    const result = PublicContentUpsertResultSchema.parse(body);

    return result;
  }

  private async uploadToStorage(
    writeUrl: string,
    content: ReadableStream<Uint8Array<ArrayBuffer>>,
  ): Promise<void> {
    const response = await fetch(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': 'text/vtt',
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      // @ts-expect-error: this is nodejs fetch
      duplex: 'half'
    });

    if (!response.ok) {
      this.logger.error({ status: response.status, body: await response.text() }, 'Unique Public API storage return an error');
      throw new Error('Unique Public API storage return an error');
    }
  }

  public async onTranscript(
    meeting: {
      subject: string;
      startDateTime: Date;
      endDateTime: Date;
      participants: { name: string; email: string }[];
      owner: { name: string; email: string };
    },
    transcript: { id: string; content: ReadableStream<Uint8Array<ArrayBuffer>> },
    recording?: { id: string; content: ReadableStream<Uint8Array<ArrayBuffer>> },
  ): Promise<void> {
    const participantsPromises = meeting.participants.map((p) =>
      this.fetchUserForScopeAccess(p.email),
    );
    const participants = (await Promise.all(participantsPromises)).filter((v) => v !== null);
    const owner = await this.fetchUserForScopeAccess(meeting.owner.email);

    if (!owner) {
      this.logger.warn({}, "owner of the meeting couldn't be found");
      return;
    }

    const path = this.mapMeetingToScope(meeting.subject, meeting.startDateTime);
    this.logger.debug({path}, 'scope')
    const scope = await this.createScope(path);

    // REVIEW: verify that organizer is also in the participants lists for a READ access
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
    await this.addScopeAccesses(scope.id, accesses);

    const transcriptUpload = await this.upsertContent({
      storeInternally: true,
      scopeId: scope.id,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: meeting.subject,
        byteSize: 1,
        metadata: {
          date: meeting.startDateTime.toISOString(),
          participants: meeting.participants,
        },
      },
    });
    await this.uploadToStorage(transcriptUpload.writeUrl, transcript.content);
    await this.upsertContent({
      storeInternally: true,
      scopeId: scope.id,
      fileUrl: transcriptUpload.readUrl,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: meeting.subject,
      },
    });

    if (recording) {
      const recordingUpload = await this.upsertContent({
        storeInternally: true,
        scopeId: scope.id,
        input: {
          key: recording.id,
          mimeType: 'text/vtt',
          title: meeting.subject,
          byteSize: 1,
          metadata: {
            date: meeting.startDateTime.toISOString(),
            participants: meeting.participants,
          },
          ingestionConfig: {
            uniqueIngestionMode: UniqueIngestionMode.SKIP_INGESTION,
          },
        },
      });
      await this.uploadToStorage(recordingUpload.writeUrl, recording.content);
    }
  }
}
