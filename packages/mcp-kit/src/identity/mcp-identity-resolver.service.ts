import { Inject, Injectable, Scope } from '@nestjs/common';
import { REQUEST } from '@nestjs/core';
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

// Narrow interface for the parts of the request we actually use.
// Avoids importing all of express.Request and casting .user.
interface McpRequest {
  user?: TokenValidationResult;
}

@Injectable({ scope: Scope.REQUEST })
export class McpIdentityResolver {
  public constructor(@Inject(REQUEST) private readonly request: McpRequest) {}

  public resolve(): McpIdentity | null {
    const user = this.request.user;  // now typed as TokenValidationResult | undefined — no cast!

    if (user === undefined) {
      return null;
    }

    return {
      userId: user.userId ?? user.sub ?? '',
      profileId: user.userProfileId ?? '',
      clientId: user.clientId ?? '',
      scopes: filter((user.scope ?? '').split(' '), isTruthy),
      resource: user.resource ?? '',
      email: user.userData?.email,
      displayName: user.userData?.displayName,
      raw: user,
    };
  }
}
