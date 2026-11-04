import { mcpRateLimitConfigSchema } from '@unique-ag/mcp-server-module';
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';

export const rateLimitConfig = registerConfig('mcpRateLimit', mcpRateLimitConfigSchema);

export type RateLimitConfigNamespaced = NamespacedConfigType<typeof rateLimitConfig>;
export type RateLimitConfig = ConfigType<typeof rateLimitConfig>;
