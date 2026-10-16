import { Injectable } from '@nestjs/common';
import { isNullish } from 'remeda';
import type { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { fromPendingDeleteExternalId, PENDING_DELETE_PREFIX } from '../utils/scope-external-id';

@Injectable()
export class FindScopeSuccessorQuery {
  // Resolves the active scope that is the same SharePoint object as a pending-delete scope.
  // Callers load the active scopes once and pass the index, so a later permissions copy can
  // reuse the lookup without listing scopes again.
  public execute(
    staleScope: Scope,
    activeScopesByExternalId: Readonly<Record<string, Scope>>,
  ): Scope | null {
    const { externalId } = staleScope;
    if (isNullish(externalId) || !externalId.startsWith(PENDING_DELETE_PREFIX)) {
      return null;
    }

    const successorExternalId = fromPendingDeleteExternalId(externalId).value;
    return activeScopesByExternalId[successorExternalId] ?? null;
  }
}
