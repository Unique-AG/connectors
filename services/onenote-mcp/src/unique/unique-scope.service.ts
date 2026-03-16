import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
import type { UniqueConfigNamespaced } from '~/config';
import { normalizeError } from '~/utils/normalize-error';
import { UNIQUE_FETCH, UNIQUE_REQUEST_HEADERS } from './unique.consts';
import {
  PublicAddScopeAccessRequestSchema,
  type PublicAddScopeAccessResult,
  PublicAddScopeAccessResultSchema,
  PublicCreateScopeRequestSchema,
  PublicCreateScopeResultSchema,
  type PublicScopeAccessSchema,
  type Scope,
} from './unique.dtos';

@Injectable()
export class UniqueScopeService {
  private readonly logger = new Logger(UniqueScopeService.name);
  private readonly apiBaseUrl: string;
  private readonly configuredHeaders: Record<string, string>;

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    @Inject(UNIQUE_REQUEST_HEADERS) configuredHeaders: Record<string, string>,
    private readonly trace: TraceService,
    config: ConfigService<UniqueConfigNamespaced, true>,
  ) {
    this.apiBaseUrl = config.get('unique.apiBaseUrl', { infer: true });
    this.configuredHeaders = configuredHeaders;
  }

  @Span()
  public async createScope(
    parentScopeId: string,
    relativePath: string,
    inheritAccess = false,
  ): Promise<Scope> {
    const span = this.trace.getSpan();
    span?.setAttribute('parent_scope_id', parentScopeId);
    span?.setAttribute('relative_path', relativePath);
    span?.setAttribute('inherit_access', inheritAccess);

    const payload = PublicCreateScopeRequestSchema.encode({
      parentScopeId,
      relativePaths: [relativePath],
      inheritAccess,
    });

    this.logger.debug(
      {
        url: `${this.apiBaseUrl}/folder`,
        method: 'POST',
        parentScopeId,
        inheritAccess,
        headers: Object.keys(this.configuredHeaders),
      },
      'Creating new organizational scope in Unique API',
    );

    try {
      const response = await this.fetch('folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = PublicCreateScopeResultSchema.refine(
        (s) => s.createdFolders.length > 0,
        'no scopes were created',
      ).parse(await response.json());

      // biome-ignore lint/style/noNonNullAssertion: we assert with zod above
      const createdScope = result.createdFolders[0]!;
      span?.setAttribute('scope_id', createdScope.id);
      span?.setAttribute('folders_created_count', result.createdFolders.length);

      this.logger.log(
        { scopeId: createdScope.id, foldersCreated: result.createdFolders.length },
        'Successfully created new organizational scope in Unique system',
      );

      return createdScope;
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          endpoint: `${this.apiBaseUrl}/folder`,
          method: 'POST',
          parentScopeId,
          relativePath,
          inheritAccess,
          configuredHeaders: this.configuredHeaders,
          errorMessage: normalized.message,
          errorName: normalized.name,
          errorStack: normalized.stack,
        },
        'Failed to create scope in Unique API',
      );
      throw error;
    }
  }

  @Span()
  public async addScopeAccesses(
    scopeId: string,
    accesses: PublicScopeAccessSchema[],
  ): Promise<PublicAddScopeAccessResult> {
    const span = this.trace.getSpan();
    span?.setAttribute('scope_id', scopeId);
    span?.setAttribute('access_count', accesses.length);

    const payload = PublicAddScopeAccessRequestSchema.encode({
      applyToSubScopes: false,
      scopeId,
      scopeAccesses: accesses,
    });

    this.logger.debug(
      {
        url: `${this.apiBaseUrl}/folder/add-access`,
        method: 'PATCH',
        scopeId,
        accessCount: accesses.length,
        headers: Object.keys(this.configuredHeaders),
      },
      'Configuring user access permissions for organizational scope',
    );

    try {
      const response = await this.fetch('folder/add-access', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = PublicAddScopeAccessResultSchema.parse(await response.json());

      this.logger.log(
        { scopeId, accessesAdded: accesses.length },
        'Successfully configured user access permissions for scope',
      );

      return result;
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          endpoint: `${this.apiBaseUrl}/folder/add-access`,
          method: 'PATCH',
          scopeId,
          accessCount: accesses.length,
          configuredHeaders: this.configuredHeaders,
          errorMessage: normalized.message,
          errorName: normalized.name,
          errorStack: normalized.stack,
        },
        'Failed to add scope accesses in Unique API',
      );
      throw error;
    }
  }
}
