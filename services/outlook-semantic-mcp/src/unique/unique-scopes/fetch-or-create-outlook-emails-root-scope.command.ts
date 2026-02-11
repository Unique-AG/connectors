import { Injectable } from "@nestjs/common";
import { UniqueScopesService } from "./unique-scopes.service";
import assert from "node:assert";
import { Span, TraceService } from "nestjs-otel";

export type UniqueEntityType = "GROUP" | "USER";
export type UniqueAccessType = "MANAGE" | "READ" | "WRITE";

export interface Scope {
  id: string;
  name: string;
  parentId: string | null;
  externalId: string | null;
  scopeAccess?: ScopeAccess[];
}

export interface ScopeWithPath extends Scope {
  path: string;
}

export interface ScopeAccess {
  type: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}

export const getRootScopePath = (userEmail: string): string =>
  `${userEmail}/Outlook Emails`;

export const getRootScopeToBeProcessed = (userEmail: string): string =>
  `${userEmail}/Outlook Pending Emails`;

@Injectable()
export class FetchOrCreateOutlookEmailsRootScopeCommand {
  constructor(
    private traceService: TraceService,
    private uniqueScopesService: UniqueScopesService,
  ) {}

  @Span()
  public async run(userEmail: string): Promise<Scope> {
    const span = this.traceService.getSpan();
    assert.ok(userEmail, `User Email: ${userEmail}`);
    span?.setAttribute(`user_emails`, userEmail);
    const scopePath = getRootScopePath(userEmail);
    const toBeProcessedScopePath = getRootScopeToBeProcessed(userEmail);
    const [rootScope, toBeProcessedScope] =
      await this.uniqueScopesService.createScopesBasedOnPaths(
        [scopePath, toBeProcessedScopePath],
        {
          inheritAccess: true,
          includePermissions: true,
        },
      );
    assert.ok(rootScope, `Could not create root scope for email: ${userEmail}`);
    assert.ok(
      toBeProcessedScope,
      `Could not create to be processed scope for email: ${userEmail}`,
    );
    span?.addEvent(`Root scopes created`);

    if (!rootScope.externalId) {
      span?.addEvent(`Locking root scope with externalId`);
      await this.uniqueScopesService.updateScopeExternalId(
        rootScope.id,
        scopePath,
      );
      span?.addEvent(`Root scope locked with externalId`);
    }
    if (!toBeProcessedScope.externalId) {
      span?.addEvent(`Locking to be processed root scope with externalId`);
      await this.uniqueScopesService.updateScopeExternalId(
        toBeProcessedScope.id,
        scopePath,
      );
      span?.addEvent(`To be processed  scope locked with externalId`);
    }
    return rootScope;
  }
}
