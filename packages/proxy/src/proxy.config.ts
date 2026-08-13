import { Redacted } from '@unique-ag/utils';
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { json } from '@unique-ag/utils/zod';
import { isEmptyish } from 'remeda';
import { z } from 'zod';

const requiredStringSchema = z.string().trim().nonempty();

const ENV_REF_PREFIX = 'os.environ/';

const envResolvableStringSchema = z.string().transform((val) => {
  if (!val.startsWith(ENV_REF_PREFIX)) {
    return val;
  }
  const varName = val.slice(ENV_REF_PREFIX.length);
  return process.env[varName] ?? '';
});

const envRequiredSecretSchema = envResolvableStringSchema
  .pipe(z.string().trim().nonempty())
  .transform((val) => new Redacted(val));

const portSchema = z.coerce.number().int().positive().max(65535);

const proxyHeadersSchema = json(z.record(z.string(), z.string()));

const baseProxyFields = {
  host: requiredStringSchema.describe('Proxy server hostname'),
  port: portSchema.describe('Proxy server port'),
  protocol: z.enum(['http', 'https']).describe('Proxy protocol'),
  sslCaBundlePath: z
    .string()
    .optional()
    .describe(
      'Path to a CA bundle used to verify the proxy TLS certificate. Needed for self-signed or ' +
        'private CAs used by the proxy server when using https proxy protocol.',
    ),
  headers: proxyHeadersSchema
    .optional()
    .describe('Custom headers for CONNECT request (JSON string in PROXY_HEADERS)'),
};

const noneProxyConfigSchema = z.object({
  authMode: z.literal('none').describe('Proxy disabled'),
});

const noAuthProxyConfigSchema = z.object({
  authMode: z.literal('no_auth').describe('Proxy enabled without authentication'),
  ...baseProxyFields,
});

const basicProxyConfigSchema = z.object({
  authMode: z.literal('username_password').describe('Basic authentication'),
  ...baseProxyFields,
  username: envRequiredSecretSchema.describe(
    'Proxy username. Use "os.environ/ENV_VAR_NAME" to read from an environment variable at runtime.',
  ),
  password: envRequiredSecretSchema.describe(
    'Proxy password. Use "os.environ/ENV_VAR_NAME" to read from an environment variable at runtime.',
  ),
});

const tlsProxyConfigSchema = z.object({
  authMode: z.literal('ssl_tls').describe('TLS client certificate authentication'),
  ...baseProxyFields,
  sslCertPath: requiredStringSchema.describe('Path to SSL/TLS client certificate'),
  sslKeyPath: requiredStringSchema.describe('Path to SSL/TLS client key'),
});

// Using z.preprocess instead of z.discriminatedUnion().prefault() because nestjs-zod passes an
// empty object {} when no PROXY_* env vars are set, and prefault only triggers when the input is
// undefined (not an empty object).
export const ProxyConfigSchema = z.preprocess(
  (input) => (isEmptyish(input) ? { authMode: 'none' } : input),
  z.discriminatedUnion('authMode', [
    noneProxyConfigSchema,
    noAuthProxyConfigSchema,
    basicProxyConfigSchema,
    tlsProxyConfigSchema,
  ]),
);

export const proxyConfig = registerConfig('proxy', ProxyConfigSchema);

export type ProxyConfig = ConfigType<typeof proxyConfig>;
export type ProxyConfigNamespaced = NamespacedConfigType<typeof proxyConfig>;

export type NoneProxyConfig = Extract<ProxyConfig, { authMode: 'none' }>;
export type NoAuthProxyConfig = Extract<ProxyConfig, { authMode: 'no_auth' }>;
export type BasicProxyConfig = Extract<ProxyConfig, { authMode: 'username_password' }>;
export type TlsProxyConfig = Extract<ProxyConfig, { authMode: 'ssl_tls' }>;
