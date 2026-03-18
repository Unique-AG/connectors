import { isIP } from 'node:net';

export function assertExternalUrl(rawUrl: string): void {
  const { hostname } = new URL(rawUrl);
  if (isIP(hostname) !== 0) {
    throw new Error(`SSRF protection: direct IP addresses are not allowed`);
  }
}
