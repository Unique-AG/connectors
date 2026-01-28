import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { coercedPositiveIntSchema, requiredStringSchema } from '../utils/zod.util';

// ==========================================
// Proxy Configuration
// ==========================================

const portSchema = coercedPositiveIntSchema.max(65535);

const proxyHeadersSchema = parseJsonEnvironmentVariable('PROXY_HEADERS').pipe(
  z.record(z.string(), z.string()),
);

const baseProxyFields = {
  host: requiredStringSchema.describe('Proxy server hostname'),
  port: portSchema.describe('Proxy server port'),
  protocol: z.enum(['http', 'https']).describe('Proxy protocol'),
  caBundlePath: z.string().optional().describe('Path to CA bundle for proxy server verification'),
  headers: proxyHeadersSchema
    .optional()
    .describe('Custom headers for CONNECT request (JSON string in PROXY_HEADERS)'),
};

const noneProxyConfigSchema = z.object({
  authMode: z.literal('none').describe('Proxy disabled'),
});

const basicProxyConfigSchema = z.object({
  authMode: z.literal('basic').describe('Basic authentication'),
  ...baseProxyFields,
  username: requiredStringSchema.describe('Proxy username'),
  password: requiredStringSchema.describe('Proxy password'),
});

const tlsProxyConfigSchema = z.object({
  authMode: z.literal('tls').describe('TLS client certificate authentication'),
  ...baseProxyFields,
  tlsCertPath: requiredStringSchema.describe('Path to TLS client certificate'),
  tlsKeyPath: requiredStringSchema.describe('Path to TLS client key'),
});

export const ProxyConfigSchema = z.discriminatedUnion('authMode', [
  noneProxyConfigSchema,
  basicProxyConfigSchema,
  tlsProxyConfigSchema,
]);

export const proxyConfig = registerConfig('proxy', ProxyConfigSchema);

export type ProxyConfig = ConfigType<typeof proxyConfig>;
export type ProxyConfigNamespaced = NamespacedConfigType<typeof proxyConfig>;

export type BasicProxyConfig = Extract<ProxyConfig, { authMode: 'basic' }>;
export type TlsProxyConfig = Extract<ProxyConfig, { authMode: 'tls' }>;
export type NoneProxyConfig = Extract<ProxyConfig, { authMode: 'none' }>;
