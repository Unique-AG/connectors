import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import pLimit from 'p-limit';
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
  type PublicGetUsersRequest,
  PublicGetUsersRequestSchema,
  type PublicScopeAccessSchema,
  type PublicUserResult,
  PublicUsersResultSchema,
  type Scope,
  ScopeAccessEntityType,
  ScopeAccessType,
} from './unique.dtos';

@Injectable()
export class UniqueService {
  private readonly logger = new Logger(UniqueService.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  // SECTION: Public API

  @Span()
  public async ingestTranscript(
    meeting: {
      subject: string;
      startDateTime: Date;
      endDateTime: Date;
      isRecurring: boolean;
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
    span?.setAttribute('is_recurring', meeting.isRecurring);

    this.logger.log(
      {
        transcriptId: transcript.id,
        participantCount: meeting.participants.length,
        meetingDate: meeting.startDateTime.toISOString(),
        isRecurring: meeting.isRecurring,
      },
      'Beginning processing of meeting transcript for ingestion',
    );

    const concurrency = this.config.get('unique.userFetchConcurrency', { infer: true });
    const limit = pLimit(concurrency);
    const participantsPromises = meeting.participants.map((p) =>
      limit(() => this.fetchUserForScopeAccess(p.email)),
    );
    const participants = (await Promise.all(participantsPromises)).filter((v) => v !== null);
    const owner = await this.fetchUserForScopeAccess(meeting.owner.email);

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

    const path = this.mapMeetingToScope(
      meeting.subject,
      meeting.startDateTime,
      meeting.isRecurring,
    );
    const scope = await this.createScope(path);
    span?.setAttribute('scope_id', scope.id);

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
    await this.addScopeAccesses(scope.id, accesses);

    this.logger.log(
      { transcriptId: transcript.id, scopeId: scope.id },
      'Beginning transcript upload to Unique system',
    );

    const transcriptUpload = await this.upsertContent({
      storeInternally: true,
      scopeId: scope.id,
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
    await this.uploadToStorage(transcriptUpload.writeUrl, transcript.content, 'text/vtt');
    await this.upsertContent({
      storeInternally: true,
      scopeId: scope.id,
      fileUrl: transcriptUpload.readUrl,
      input: {
        key: transcript.id,
        mimeType: 'text/vtt',
        title: `${meeting.subject}.vtt`,
      },
    });
    span?.addEvent('ingestion_completed', {
      transcriptId: transcript.id,
      scopeId: scope.id,
    });

    this.logger.log(
      {
        transcriptId: transcript.id,
        scopeId: scope.id,
      },
      'Successfully completed meeting transcript ingestion process',
    );
  }

  // !SECTION: Public API

  // SECTION: Unique API Methods

  @Span()
  private async fetchUserForScopeAccess(email: string): Promise<PublicUserResult | null> {
    const span = this.trace.getSpan();

    const baseUrl = this.config.get('unique.apiBaseUrl', { infer: true });

    // Create two parallel requests - one with email param, one with userName param (both using email value)
    const fetchByEmailOrUsername = async (
      payloadInput: PublicGetUsersRequest,
    ): Promise<PublicUserResult | null> => {
      const payload = PublicGetUsersRequestSchema.encode(payloadInput);
      const endpoint = new URL('users', baseUrl);
      const params = new URLSearchParams();
      Object.entries(payload).forEach(([key, value]) => {
        params.append(key, String(value));
      });
      const qs = params.toString();
      if (qs) {
        endpoint.search = qs;
      }

      this.logger.debug(
        { endpoint: endpoint.origin + endpoint.pathname },
        'Searching for user in Unique system by email or username',
      );

      const response = await fetch(endpoint, {
        method: 'GET',
        headers: this.getAuthHeaders(),
      });

      if (!response.ok) {
        this.logger.warn(
          { status: response.status, endpoint: endpoint.origin + endpoint.pathname },
          'Failed to locate user in Unique system by email or username',
        );
        return null;
      }

      const body = await response.json();
      const result = PublicUsersResultSchema.parse(body);
      return result.users.at(0) ?? null;
    };

    // Execute both requests in parallel
    const [userByEmail, userByUserName] = await Promise.all([
      fetchByEmailOrUsername({ email }),
      fetchByEmailOrUsername({ userName: email }),
    ]);

    // Return whichever found a user (prefer email match if both succeed)
    const userFound = userByEmail ?? userByUserName;

    span?.setAttribute('user_found', !!userFound);
    span?.setAttribute('found_by_email', !!userByEmail);
    span?.setAttribute('found_by_username', !!userByUserName);

    this.logger.debug(
      {
        found: !!userFound,
        foundByEmail: !!userByEmail,
        foundByUserName: !!userByUserName,
        searchMethod: 'email_and_username',
      },
      'Completed user search operation in Unique system',
    );

    return userFound;
  }

  @Span()
  private async createScope(path: string): Promise<Scope> {
    const span = this.trace.getSpan();
    span?.setAttribute('path', path);

    const payload = PublicCreateScopeRequestSchema.encode({ paths: [path], inheritAccess: false });
    const endpoint = new URL('folder', this.config.get('unique.apiBaseUrl', { infer: true }));

    this.logger.debug(
      { endpoint: endpoint.href, pathCount: payload.paths.length },
      'Creating new organizational scope in Unique API',
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
        'Unique Public API rejected scope creation request with error',
      );
      assert.fail(`Unique Public API return an error for content upsert: ${response.status}`);
    }
    const body = await response.json();
    const result = PublicCreateScopeResultSchema.refine(
      (s) => s.createdFolders.length > 0,
      'no scopes were created',
    ).parse(body);

    // biome-ignore lint/style/noNonNullAssertion: we assert with zod above
    const createdScope = result.createdFolders[0]!;
    span?.setAttribute('scope_id', createdScope.id);
    span?.setAttribute('folders_created_count', result.createdFolders.length);

    this.logger.log(
      { scopeId: createdScope.id, foldersCreated: result.createdFolders.length },
      'Successfully created new organizational scope in Unique system',
    );
    this.logger.debug(
      { createdFolders: result.createdFolders },
      'Detailed information about created scope structure',
    );

    return createdScope;
  }

  @Span()
  private async addScopeAccesses(
    scope: string,
    accesses: PublicScopeAccessSchema[],
  ): Promise<PublicAddScopeAccessResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('scope_id', scope);
    span?.setAttribute('access_count', accesses.length);

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
      'Configuring user access permissions for organizational scope',
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
        'Unique Public API rejected scope access configuration with error',
      );
      assert.fail(`Unique Public API return an error for content upsert: ${response.status}`);
    }
    const body = await response.json();
    const result = PublicAddScopeAccessResultSchema.parse(body);

    this.logger.log(
      { scopeId: scope, accessesAdded: accesses.length },
      'Successfully configured user access permissions for scope',
    );

    return result;
  }

  @Span()
  private async upsertContent(
    content: PublicContentUpsertRequest,
  ): Promise<PublicContentUpsertResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('scope_id', content.scopeId ?? '');
    span?.setAttribute('content_key', content.input.key);
    span?.setAttribute('mime_type', content.input.mimeType);
    span?.setAttribute('store_internally', content.storeInternally);
    span?.setAttribute('has_file_url', !!content.fileUrl);

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
      'Creating or updating content record in Unique system',
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
        'Unique Public API rejected content creation request with error',
      );
      assert.fail(`Unique Public API return an error for content upsert: ${response.status}`);
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
      'Successfully created or updated content record in Unique system',
    );

    return {
      ...result,
      writeUrl: this.correctWriteUrl(result.writeUrl),
    };
  }

  @Span()
  private async uploadToStorage(
    writeUrl: string,
    content: ReadableStream<Uint8Array<ArrayBuffer>>,
    mime: string,
  ): Promise<void> {
    const span = this.trace.getSpan();

    // Extract only the storage account hostname for logging (no query params or paths with sensitive data)
    const urlObj = new URL(writeUrl);
    const storageEndpoint = urlObj.origin;
    span?.setAttribute('storage_endpoint', storageEndpoint);

    this.logger.debug({ storageEndpoint }, 'Beginning content upload to Unique storage system');

    const response = await fetch(writeUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': mime,
        'x-ms-blob-type': 'BlockBlob',
      },
      body: content,
      // @ts-expect-error: this is nodejs fetch and requires `half` to be specified as per fetch WHATWG
      // and nodejs types get merged with browser types which do not have such property
      // - see https://undici.nodejs.org/#/?id=requestduplex
      duplex: 'half',
    });

    if (!response.ok) {
      span?.setAttribute('error', true);
      span?.setAttribute('http_status', response.status);
      this.logger.error(
        { status: response.status, storageEndpoint },
        'Unique storage system rejected content upload with error',
      );
      assert.fail(`Unique Public API storage return an error: ${response.status}`);
    }

    span?.setAttribute('http_status', response.status);
    this.logger.debug(
      { storageEndpoint },
      'Successfully completed content upload to storage system',
    );
  }

  // !SECTION: Unique API Methods

  // SECTION: Helpers

  private getAuthHeaders(): Record<string, string> {
    const uniqueConfig = this.config.get('unique', { infer: true });
    return {
      'x-api-version': uniqueConfig.apiVersion,
      ...uniqueConfig.serviceExtraHeaders,
    };
  }

  private mapMeetingToScope(subject: string, happenedAt: Date, recurring = false): string {
    const rootScopePath = this.config.get('unique.rootScopePath', { infer: true });
    // biome-ignore lint/style/noNonNullAssertion: iso string is always with T
    const formattedDate = happenedAt.toISOString().split('T').at(0)!;
    const sanitizedSubject =
      subject
        .replace(/[^a-zA-Z0-9\s/-]/g, '-')
        .replace(/-+/g, '-')
        .replace(/^-|-$/g, '') || 'Untitled Meeting';
    return recurring
      ? `/${rootScopePath}/${sanitizedSubject}/${formattedDate}`
      : `/${rootScopePath}/${sanitizedSubject} - ${formattedDate}`;
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
      `scoped/upload?key=${encodeURIComponent(key)}`,
      uniqueConfig.ingestionServiceBaseUrl,
    ).toString();
  }

  // !SECTION: Helpers
}
