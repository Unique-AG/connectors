import { mcpRateLimitConfigSchema } from '@unique-ag/mcp-server-module';
import { ConfigType, NamespacedConfigType } from '@proventuslabs/nestjs-zod';
import { registerConfig } from './register-config';

export const rateLimitConfig = registerConfig('mcpRateLimit', mcpRateLimitConfigSchema);

export type RateLimitConfigNamespaced = NamespacedConfigType<typeof rateLimitConfig>;
export type RateLimitConfig = ConfigType<typeof rateLimitConfig>;
