import { SetMetadata } from '@nestjs/common';

export const PER_IP_CEILING_KEY = 'mcp-oauth:per-ip-ceiling';
export const PER_IP_CEILING_NAME = 'per-ip-ceiling';

export interface PerIpCeilingOptions {
  limit: number;
  ttl: number;
}

/** Per-IP cap for a route keyed per credential, so one address cannot escape by varying it. */
export const PerIpCeiling = (options: PerIpCeilingOptions) =>
  SetMetadata(PER_IP_CEILING_KEY, options);
