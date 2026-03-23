import { Inject, Injectable, Scope } from '@nestjs/common';
import { REQUEST } from '@nestjs/core';
import type { Request } from 'express';
import type { McpIdentity } from './mcp-identity.interface';

// Provisional shape — refined in AUTH-002
interface TokenValidationResult {
  sub?: string;
  userId?: string;
  clientId?: string;
  scope?: string;
  resource?: string;
  userProfileId?: string;
  userData?: {
    email?: string;
    displayName?: string;
  };
}

@Injectable({ scope: Scope.REQUEST })
export class McpIdentityResolver {
  public constructor(@Inject(REQUEST) private readonly request: Request) {}

  public resolve(): McpIdentity | null {
    const user = this.request.user as TokenValidationResult | undefined;

    if (!user) {
      return null;
    }

    const userId = user.userId ?? user.sub ?? '';
    const profileId = user.userProfileId ?? '';
    const clientId = user.clientId ?? '';
    const scopes = user.scope ? user.scope.split(' ').filter(Boolean) : [];
    const resource = user.resource ?? '';

    return {
      userId,
      profileId,
      clientId,
      email: user.userData?.email,
      displayName: user.userData?.displayName,
      scopes,
      resource,
      raw: user,
    };
  }
}
