# HTTP Proxy Support for SharePoint Connector

## Context

The SharePoint connector needs internet access to call Microsoft Graph API and SharePoint REST API. Some deployments (e.g., BNPP) can only connect to the internet via an HTTP proxy server.

**Ticket:** UN-16576

## Requirements

- Proxy ALL external calls: Microsoft APIs (Graph, SharePoint REST, MS login) and Unique API (when in external mode)
- Support two proxy authentication modes: basic (username/password) and TLS (client certificate)
- Configuration via environment variables
- Helm chart creates ConfigMap for proxy settings

## Design

### Configuration Schema

File: `src/config/proxy.schema.ts`

Uses Zod discriminated union to enforce required fields per auth mode:

```typescript
import { z } from 'zod';
import { coercedPositiveIntSchema, requiredStringSchema } from '../utils/zod.util';

const portSchema = coercedPositiveIntSchema.max(65535);

const baseProxyFields = {
  host: requiredStringSchema,
  port: portSchema,
  protocol: z.enum(['http', 'https']),
  caBundlePath: z.string().optional(),
  headers: z.record(z.string()).optional(),
};

export const ProxyConfigSchema = z.discriminatedUnion('authMode', [
  z.object({
    authMode: z.literal('none'),
  }),
  z.object({
    authMode: z.literal('basic'),
    ...baseProxyFields,
    username: requiredStringSchema,
    password: requiredStringSchema,
  }),
  z.object({
    authMode: z.literal('tls'),
    ...baseProxyFields,
    tlsCertPath: requiredStringSchema,
    tlsKeyPath: requiredStringSchema,
  }),
]);
```

**Environment variables by mode:**

| Mode | Required | Optional |
|------|----------|----------|
| `none` | — | — |
| `basic` | `PROXY_HOST`, `PROXY_PORT`, `PROXY_PROTOCOL`, `PROXY_USERNAME`, `PROXY_PASSWORD` | `PROXY_CA_BUNDLE_PATH`, `PROXY_HEADERS` |
| `tls` | `PROXY_HOST`, `PROXY_PORT`, `PROXY_PROTOCOL`, `PROXY_TLS_CERT_PATH`, `PROXY_TLS_KEY_PATH` | `PROXY_CA_BUNDLE_PATH`, `PROXY_HEADERS` |

### ProxyService

File: `src/proxy/proxy.service.ts`

Centralized service that creates and manages undici dispatchers:

```typescript
export type ProxyMode = 'always' | 'external-only';

@Injectable()
export class ProxyService implements OnModuleDestroy {
  private readonly dispatcher: Dispatcher;
  private readonly noProxyDispatcher: Dispatcher;
  private readonly isExternalMode: boolean;

  public constructor(configService: ConfigService<Config, true>) {
    const proxyConfig = configService.get('proxy', { infer: true });
    const uniqueConfig = configService.get('unique', { infer: true });
    
    this.isExternalMode = uniqueConfig.serviceAuthMode === 'external';
    this.noProxyDispatcher = new Agent();
    this.dispatcher = this.createDispatcher(proxyConfig);
  }

  public getDispatcher(mode: ProxyMode = 'always'): Dispatcher {
    if (mode === 'external-only' && !this.isExternalMode) {
      return this.noProxyDispatcher;
    }
    return this.dispatcher;
  }

  public async onModuleDestroy(): Promise<void> {
    await this.dispatcher.close();
    await this.noProxyDispatcher.close();
  }

  private createDispatcher(proxyConfig: ProxyConfig): Dispatcher {
    const sharedOptions = {
      bodyTimeout: 60_000,
      headersTimeout: 30_000,
      connectTimeout: 15_000,
    };

    if (proxyConfig.authMode === 'none') {
      return new Agent(sharedOptions);
    }

    const proxyUrl = this.buildProxyUrl(proxyConfig);
    const proxyOptions: ProxyAgent.Options = {
      uri: proxyUrl,
      ...sharedOptions,
    };

    if (proxyConfig.authMode === 'basic') {
      const credentials = Buffer.from(
        `${proxyConfig.username}:${proxyConfig.password}`
      ).toString('base64');
      proxyOptions.token = `Basic ${credentials}`;
    }

    if (proxyConfig.authMode === 'tls') {
      proxyOptions.requestTls = {
        cert: readFileSync(proxyConfig.tlsCertPath),
        key: readFileSync(proxyConfig.tlsKeyPath),
      };
    }

    if (proxyConfig.caBundlePath) {
      proxyOptions.proxyTls = { ca: readFileSync(proxyConfig.caBundlePath) };
    }

    return new ProxyAgent(proxyOptions);
  }

  private buildProxyUrl(proxyConfig: BasicProxyConfig | TlsProxyConfig): string {
    return `${proxyConfig.protocol}://${proxyConfig.host}:${proxyConfig.port}`;
  }
}
```

### Client Integration

| Client | Mode | Reason |
|--------|------|--------|
| SharepointRestHttpService | `'always'` | MS API - always external |
| GraphClientFactory | `'always'` | MS API - always external |
| CertificateAuthStrategy (MSAL) | `'always'` | MS login - always external |
| ClientSecretAuthStrategy (MSAL) | `'always'` | MS login - always external |
| UniqueGraphqlClient | `'external-only'` | Unique API - only when external |
| IngestionHttpClient | `'external-only'` | Unique API - only when external |
| HttpClientService (Zitadel) | `'external-only'` | Zitadel auth - only when external |

### Helm Chart

**values.yaml additions:**

```yaml
proxy:
  authMode: none
  # host: proxy.example.com
  # port: 8080
  # protocol: http
  # username: ""
  # tlsCertPath: /app/proxy-certs/client.crt
  # tlsKeyPath: /app/proxy-certs/client.key
  # caBundlePath: /app/proxy-certs/ca.crt
```

**templates/proxy-configmap.yaml:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sharepoint-connector-proxy-config
  labels:
    {{- include "chart.labels" . | nindent 4 }}
data:
  PROXY_AUTH_MODE: {{ .Values.proxy.authMode | quote }}
  {{- if ne .Values.proxy.authMode "none" }}
  PROXY_HOST: {{ .Values.proxy.host | quote }}
  PROXY_PORT: {{ .Values.proxy.port | quote }}
  PROXY_PROTOCOL: {{ .Values.proxy.protocol | quote }}
  {{- end }}
  {{- if eq .Values.proxy.authMode "basic" }}
  PROXY_USERNAME: {{ .Values.proxy.username | quote }}
  {{- end }}
  {{- if eq .Values.proxy.authMode "tls" }}
  PROXY_TLS_CERT_PATH: {{ .Values.proxy.tlsCertPath | quote }}
  PROXY_TLS_KEY_PATH: {{ .Values.proxy.tlsKeyPath | quote }}
  {{- end }}
  {{- if .Values.proxy.caBundlePath }}
  PROXY_CA_BUNDLE_PATH: {{ .Values.proxy.caBundlePath | quote }}
  {{- end }}
```

**Secrets:** For `PROXY_PASSWORD` in basic auth mode, users create a Secret externally and reference via `connector.envVars`.

**extraEnvCM reference:**

```yaml
connector:
  extraEnvCM:
    - sharepoint-connector-proxy-config
```

## Files to Change

| File | Change |
|------|--------|
| `src/config/proxy.schema.ts` | New - Zod schema |
| `src/proxy/proxy.module.ts` | New - NestJS module |
| `src/proxy/proxy.service.ts` | New - Dispatcher factory |
| `src/shared/services/http-client.service.ts` | Inject ProxyService |
| `src/microsoft-apis/sharepoint-rest/sharepoint-rest-http.service.ts` | Inject ProxyService |
| `src/microsoft-apis/graph/graph-client.factory.ts` | Inject ProxyService, pass fetchOptions |
| `src/microsoft-apis/auth/strategies/certificate-auth.strategy.ts` | Configure MSAL with proxy |
| `src/microsoft-apis/auth/strategies/client-secret-auth.strategy.ts` | Configure MSAL with proxy |
| `src/unique-api/clients/unique-graphql.client.ts` | Inject ProxyService, custom fetch |
| `src/unique-api/clients/ingestion-http.client.ts` | Inject ProxyService |
| `deploy/helm-charts/.../values.yaml` | Add proxy section |
| `deploy/helm-charts/.../templates/proxy-configmap.yaml` | New - ConfigMap template |
| Existing test files | Mock ProxyService where needed |

## Testing

No new tests. Update existing tests to mock ProxyService where injection is added.

## References

- [Undici ProxyAgent documentation](https://undici.nodejs.org/#/docs/api/ProxyAgent)
- [Python proxy implementation](https://github.com/Unique-AG/ai/blob/main/tool_packages/unique_web_search/src/unique_web_search/services/client/proxy_config.py)
- [MS Graph SDK proxy configuration](https://github.com/microsoftgraph/msgraph-sdk-javascript/issues/1646)
