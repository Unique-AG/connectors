import { Injectable, Logger } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import {
  PublicAddScopeAccessRequestSchema,
  type PublicAddScopeAccessResult,
  PublicAddScopeAccessResultSchema,
  PublicCreateScopeRequestSchema,
  PublicCreateScopeResultSchema,
  type PublicScopeAccessSchema,
  type Scope,
} from './unique.dtos';
import { UniqueApiClient } from './unique-api.client';

@Injectable()
export class UniqueScopeService {
  private readonly logger = new Logger(UniqueScopeService.name);

  public constructor(
    private readonly api: UniqueApiClient,
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

    const body = await this.api.post('folder', payload);
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

    const body = await this.api.patch('folder/add-access', payload);
    const result = PublicAddScopeAccessResultSchema.parse(body);

    this.logger.log(
      { scopeId, accessesAdded: accesses.length },
      'Successfully configured user access permissions for scope',
    );

    return result;
  }
}
