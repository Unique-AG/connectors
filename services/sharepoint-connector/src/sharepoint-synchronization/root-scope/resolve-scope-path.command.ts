import assert from 'node:assert';
import { Injectable } from '@nestjs/common';
import { UniqueScopesService } from '../../unique-api/unique-scopes/unique-scopes.service';
import type { Scope } from '../../unique-api/unique-scopes/unique-scopes.types';
import { createSmeared, Smeared } from '../../utils/smeared';

@Injectable()
export class ResolveScopePathCommand {
  public constructor(private readonly uniqueScopesService: UniqueScopesService) {}

  // Walks up from `scope` to the root, granting READ permission to `userId` on each ancestor
  // first so that `getScopeById` can read it. Returns the absolute path including `scope.name`.
  public async execute(scope: Scope, userId: string): Promise<Smeared> {
    const pathSegments = [scope.name];
    let currentScope: Scope = scope;

    while (currentScope.parentId) {
      await this.uniqueScopesService.createScopeAccesses(currentScope.parentId, [
        { type: 'READ', entityId: userId, entityType: 'USER' },
      ]);

      const parent = await this.uniqueScopesService.getScopeById(currentScope.parentId);

      assert.ok(
        parent,
        `Parent scope ${currentScope.parentId} not found for scope ${currentScope.id}`,
      );

      pathSegments.unshift(parent.name);
      currentScope = parent;
    }

    return createSmeared(`/${pathSegments.join('/')}`);
  }
}
