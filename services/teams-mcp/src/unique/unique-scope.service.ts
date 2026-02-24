import { Inject, Injectable, Logger } from '@nestjs/common';
import type { FetchFn } from '@qfetch/qfetch';
import { Span, TraceService } from 'nestjs-otel';
import { UNIQUE_FETCH } from './unique.consts';
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

  public constructor(
    @Inject(UNIQUE_FETCH) private readonly fetch: FetchFn,
    private readonly trace: TraceService,
  ) {}

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
      { parentScopeId, inheritAccess },
      'Creating new organizational scope in Unique API',
    );

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
      { scopeId, accessCount: accesses.length },
      'Configuring user access permissions for organizational scope',
    );

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
  }
}
