import { SetMetadata } from '@nestjs/common';

export const PER_IP_CEILING_KEY = 'mcp-oauth:per-ip-ceiling';
export const PER_IP_CEILING_NAME = 'per-ip-ceiling';

export interface PerIpCeilingOptions {
  limit: number;
  ttl: number;
}

/**
 * A second cap, counted per IP, for a route whose main bucket is keyed per credential. It keeps
 * a single address from escaping every limit by varying the credential on each request.
 */
export const PerIpCeiling = (options: PerIpCeilingOptions) =>
  SetMetadata(PER_IP_CEILING_KEY, options);
