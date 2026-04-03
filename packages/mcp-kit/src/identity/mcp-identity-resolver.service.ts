import { Inject, Injectable, Scope } from '@nestjs/common';
import { REQUEST } from '@nestjs/core';
import { filter, isTruthy } from 'remeda';
import { z } from 'zod';
import type { McpIdentity } from './mcp-identity.interface.js';

const TokenSchema = z
  .object({
    sub: z.string().optional(),
    userId: z.string().optional(),
    clientId: z.string().optional(),
    scope: z.string().optional(),
    resource: z.string().optional(),
    userProfileId: z.string().optional(),
    userData: z
      .object({
        email: z.string().optional(),
        displayName: z.string().optional(),
      })
      .optional(),
  })
  .passthrough()
  .transform((token): McpIdentity => ({
    userId: token.userId ?? token.sub ?? '',
    profileId: token.userProfileId ?? '',
    clientId: token.clientId ?? '',
    scopes: filter((token.scope ?? '').split(' '), isTruthy),
    resource: token.resource ?? '',
    email: token.userData?.email,
    displayName: token.userData?.displayName,
    raw: token,
  }));

/**
 * Narrow interface covering only the request fields this service reads.
 * Avoids importing the full `express.Request` type and casting `req.user`.
 */
interface McpRequest {
  user?: unknown;
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
    const user = this.request.user;
    if (user === undefined) {
      return null;
    }
    const result = TokenSchema.safeParse(user);
    if (!result.success) return null;
    return { ...result.data, raw: user };
  }
}
