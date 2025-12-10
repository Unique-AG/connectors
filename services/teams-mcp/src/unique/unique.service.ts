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

  private getAuthHeaders(): Record<string, string> {
    const uniqueConfig = this.config.get('unique', { infer: true });
    const baseHeaders: Record<string, string> = {
      'x-api-version': uniqueConfig.apiVersion,
    };

    if (uniqueConfig.serviceAuthMode === 'cluster_local') {
      // For cluster_local mode, use the extra headers from config
      const extraHeaders = uniqueConfig.serviceExtraHeaders;
      return {
        ...baseHeaders,
        ...extraHeaders,
      };
    }

    // For external mode, use app key and other auth details
    return {
      ...baseHeaders,
      Authorization: `Bearer ${uniqueConfig.appKey.value}`,
      'x-app-id': uniqueConfig.appId,
      'x-company-id': uniqueConfig.authCompanyId,
      'x-user-id': uniqueConfig.authUserId,
    };
  }

  private mapMeetingToScope(subject: string, happenedAt: Date, recurring = false): string {
    const rootScopePath = this.config.get('unique.rootScopePath', { infer: true });
    // biome-ignore lint/style/noNonNullAssertion: iso string is always with T
    const formattedDate = happenedAt.toISOString().split('T').at(0)!;
    // TODO: remove any non-alpha numeric characters from subject
    return recurring
      ? `/${rootScopePath}/${subject}/${formattedDate}`
      : `/${rootScopePath}/${subject} - ${formattedDate}`;
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

    this.logger.debug(
      { endpoint: endpoint.origin + endpoint.pathname },
      'Fetching user from Unique API',
    );

    const response = await fetch(endpoint, {
      method: 'GET',
      headers: this.getAuthHeaders(),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.origin + endpoint.pathname },
        'Unique Public API returned an error for user fetch',
      );
      throw new Error('Unique Public API return an error ');
    }
    const body = await response.json();
    const result = PublicUsersResultSchema.parse(body);

    const userFound = result.users.at(0) ?? null;
    this.logger.debug(
      { found: !!userFound, userCount: result.users.length },
      'User fetch completed',
    );

    return userFound;
  }

  private async createScope(path: string): Promise<Scope> {
    const payload = PublicCreateScopeRequestSchema.encode({ paths: [path] });
    const endpoint = new URL('folder', this.config.get('unique.apiBaseUrl', { infer: true }));

    this.logger.debug(
      { endpoint: endpoint.href, pathCount: payload.paths.length },
      'Creating scope',
    );

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders(),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.href },
        'Unique Public API returned an error for scope creation',
      );
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    const result = PublicCreateScopeResultSchema.refine(
      (s) => s.createdFolders.length > 0,
      'no scopes were created',
    ).parse(body);

    // biome-ignore lint/style/noNonNullAssertion: we assert with zod above
    const createdScope = result.createdFolders[0]!;
    this.logger.log(
      { scopeId: createdScope.id, foldersCreated: result.createdFolders.length },
      'Scope created successfully',
    );
    this.logger.debug({ createdFolders: result.createdFolders }, 'Scope creation details');

    return createdScope;
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

    this.logger.debug(
      { endpoint: endpoint.href, scopeId: scope, accessCount: accesses.length },
      'Adding scope accesses',
    );

    const response = await fetch(endpoint, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders(),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, endpoint: endpoint.href, scopeId: scope },
        'Unique Public API returned an error for adding scope accesses',
      );
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    const result = PublicAddScopeAccessResultSchema.parse(body);

    this.logger.log(
      { scopeId: scope, accessesAdded: accesses.length },
      'Scope accesses added successfully',
    );

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

    this.logger.debug(
      {
        endpoint: endpoint.href,
        scopeId: content.scopeId,
        contentKey: content.input.key,
        mimeType: content.input.mimeType,
        storeInternally: content.storeInternally,
        hasFileUrl: !!content.fileUrl,
      },
      'Upserting content',
    );

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...this.getAuthHeaders(),
      },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      this.logger.error(
        {
          status: response.status,
          endpoint: endpoint.href,
          scopeId: content.scopeId,
          contentKey: content.input.key,
        },
        'Unique Public API returned an error for content upsert',
      );
      throw new Error('Unique Public API return an error');
    }
    const body = await response.json();
    const result = PublicContentUpsertResultSchema.parse(body);

    this.logger.log(
      {
        scopeId: content.scopeId,
        contentKey: content.input.key,
        mimeType: content.input.mimeType,
        hasWriteUrl: !!result.writeUrl,
        hasReadUrl: !!result.readUrl,
      },
      'Content upserted successfully',
    );

    return {
      ...result,
      writeUrl: this.correctWriteUrl(result.writeUrl)
    };
  }

  private async uploadToStorage(
    writeUrl: string,
    content: ReadableStream<Uint8Array<ArrayBuffer>>,
  ): Promise<void> {
    // Extract only the storage account hostname for logging (no query params or paths with sensitive data)
    const urlObj = new URL(writeUrl);
    const storageEndpoint = `${urlObj.protocol}//${urlObj.hostname}`;

    this.logger.debug({ storageEndpoint }, 'Uploading content to storage');

    const response = await fetch(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': 'text/vtt',
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      // @ts-expect-error: this is nodejs fetch
      duplex: 'half',
    });

    if (!response.ok) {
      this.logger.error(
        { status: response.status, storageEndpoint },
        'Unique Public API storage returned an error',
      );
      throw new Error('Unique Public API storage return an error');
    }

    this.logger.debug({ storageEndpoint }, 'Content uploaded to storage successfully');
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
    this.logger.log(
      {
        transcriptId: transcript.id,
        recordingId: recording?.id,
        participantCount: meeting.participants.length,
        meetingDate: meeting.startDateTime.toISOString(),
      },
      'Processing meeting transcript',
    );

    const participantsPromises = meeting.participants.map((p) =>
      this.fetchUserForScopeAccess(p.email),
    );
    const participants = (await Promise.all(participantsPromises)).filter((v) => v !== null);
    const owner = await this.fetchUserForScopeAccess(meeting.owner.email);

    if (!owner) {
      this.logger.warn(
        { participantCount: meeting.participants.length },
        "Owner of the meeting couldn't be found in Unique",
      );
      return;
    }

    this.logger.debug(
      { foundParticipants: participants.length, totalParticipants: meeting.participants.length },
      'Participants resolved',
    );

    const path = this.mapMeetingToScope(meeting.subject, meeting.startDateTime);
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

    this.logger.log({ transcriptId: transcript.id, scopeId: scope.id }, 'Uploading transcript');

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
      this.logger.log({ recordingId: recording.id, scopeId: scope.id }, 'Uploading recording');

      const recordingUpload = await this.upsertContent({
        storeInternally: true,
        scopeId: scope.id,
        input: {
          key: recording.id,
          mimeType: 'video/mp4',
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
      await this.upsertContent({
        storeInternally: true,
        scopeId: scope.id,
        fileUrl: recordingUpload.readUrl,
        input: {
          key: transcript.id,
          mimeType: 'video/mp4',
          title: meeting.subject,
        },
      });
    }

    this.logger.log(
      {
        transcriptId: transcript.id,
        recordingId: recording?.id,
        scopeId: scope.id,
      },
      'Meeting transcript processing completed',
    );
  }

  // HACK:
  // When running in internal auth mode, rewrite the writeUrl to route through the ingestion
  // service's scoped upload endpoint. This enables internal services to upload files without
  // requiring external network access (hairpinning).
  // Ideally we should fix this somehow in the service itself by using a separate property or make
  // writeUrl configurable, but for now this hack lets us avoid hairpinning issues in the internal
  // upload flows.
  private correctWriteUrl(writeUrl: string): string {
    const uniqueConfig = this.config.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode === 'external') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    if (!key) throw new Error('writeUrl is missing key parameter');

    return new URL(
      `/scoped/upload?key=${encodeURIComponent(key)}`,
      uniqueConfig.ingestionServiceBaseUrl,
    ).toString();
  }
}
