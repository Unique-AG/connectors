import { Injectable } from "@nestjs/common";

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

@Injectable()
export class FetchOrCreateOutlookEmailsRootScopeCommand {
  public async run(userEmail: string): Promise<Scope> {}
}
