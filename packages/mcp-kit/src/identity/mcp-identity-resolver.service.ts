import { Inject, Injectable, Scope } from '@nestjs/common';
import { REQUEST } from '@nestjs/core';
import { filter, isTruthy } from 'remeda';
import type { McpIdentity } from './mcp-identity.interface';

/**
 * Provisional shape of the validated token payload attached to the request as `req.user`.
 * Refined in AUTH-002.
 */
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

/**
 * Narrow interface covering only the request fields this service reads.
 * Avoids importing the full `express.Request` type and casting `req.user`.
 */
interface McpRequest {
  user?: TokenValidationResult;
}

/**
 * REQUEST-scoped service that extracts a normalised `McpIdentity` from the current HTTP request.
 * Returns `null` when no authenticated user is present on the request.
 */
@Injectable({ scope: Scope.REQUEST })
export class McpIdentityResolver {
  public constructor(@Inject(REQUEST) private readonly request: McpRequest) {}

  /** Maps `request.user` to a `McpIdentity`, or returns `null` if unauthenticated. */
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
