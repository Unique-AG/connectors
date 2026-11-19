import { createHash } from 'node:crypto';
import type { ThrottlerGetTrackerFunction } from '@nestjs/throttler';

/**
 * Keys the token endpoint's rate limit by IP and credential rather than by IP alone. Every
 * user of a tenant reaches the server through the same backend egress IP, so a per-IP bucket
 * is shared by all of them, while a legitimate client presents each code or refresh token once.
 * Requests without a credential still share the per-IP bucket.
 */
export const tokenCredentialTracker: ThrottlerGetTrackerFunction = (req) => {
  const credential = credentialOf(req.body);
  return `${req.ip}:${createHash('sha256').update(credential).digest('hex')}`;
};

function credentialOf(body: unknown): string {
  if (typeof body !== 'object' || body === null) {
    return '';
  }
  const { refresh_token: refreshToken, code } = body as Record<string, unknown>;
  if (typeof refreshToken === 'string') {
    return refreshToken;
  }
  return typeof code === 'string' ? code : '';
}
