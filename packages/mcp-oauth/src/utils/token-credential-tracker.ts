import { createHash } from 'node:crypto';
import type { ThrottlerGetTrackerFunction } from '@nestjs/throttler';

/**
 * Keys by IP and credential hash. A tenant's users share one egress IP, so per-IP alone would
 * throttle all of them. The route's `PerIpCeiling` still bounds one address.
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
