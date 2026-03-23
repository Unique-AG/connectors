import { Inject, Injectable, Scope } from '@nestjs/common';
import { REQUEST } from '@nestjs/core';
import type { Request } from 'express';
import { filter, isTruthy } from 'remeda';
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

    const userId = user.userId !== undefined ? user.userId : (user.sub !== undefined ? user.sub : '');
    const profileId = user.userProfileId !== undefined ? user.userProfileId : '';
    const clientId = user.clientId !== undefined ? user.clientId : '';
    const scopeString = user.scope !== undefined ? user.scope : '';
    const scopes = filter(scopeString.split(' '), isTruthy);
    const resource = user.resource !== undefined ? user.resource : '';
    const email = user.userData !== undefined ? user.userData.email : undefined;
    const displayName = user.userData !== undefined ? user.userData.displayName : undefined;

    return {
      userId,
      profileId,
      clientId,
      email,
      displayName,
      scopes,
      resource,
      raw: user,
    };
  }
}
