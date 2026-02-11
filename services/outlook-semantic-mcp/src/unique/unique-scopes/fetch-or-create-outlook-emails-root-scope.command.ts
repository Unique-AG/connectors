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
    span?.addEvent(`Creating root scope`);
    const [rootScope] = await this.uniqueScopesService.createScopesBasedOnPaths(
      [scopePath],
      {
        inheritAccess: true,
        includePermissions: true,
      },
    );
    span?.addEvent(`Root scope created`);
    assert.ok(rootScope, `Could not create root scope for email: ${userEmail}`);
    if (!rootScope.externalId) {
      span?.addEvent(`Locking root scope with externalId`);
      await this.uniqueScopesService.updateScopeExternalId(
        rootScope.id,
        scopePath,
      );
      span?.addEvent(`Root scope locked with externalId`);
    }
    return rootScope;
  }
}
