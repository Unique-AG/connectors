# HTTP Proxy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable SharePoint connector to route HTTP requests through an internet proxy server.

**Architecture:** Centralized `ProxyService` creates undici `ProxyAgent` or `Agent` based on configuration. All HTTP clients inject this service and use its dispatcher. Proxy mode (`always` vs `external-only`) determines when proxy is applied.

**Tech Stack:** NestJS, undici (ProxyAgent), Zod, @azure/msal-node, graphql-request, Helm

**Design Document:** `docs/plans/2026-01-28-http-proxy-design.md`

---

## Task 1: Add Proxy Configuration Schema

**Files:**
- Create: `services/sharepoint-connector/src/config/proxy.schema.ts`
- Modify: `services/sharepoint-connector/src/config/index.ts`

**Step 1: Create proxy schema file**

```typescript
// services/sharepoint-connector/src/config/proxy.schema.ts
import { ConfigType, NamespacedConfigType, registerConfig } from '@proventuslabs/nestjs-zod';
import { z } from 'zod';
import { parseJsonEnvironmentVariable } from '../utils/config.util';
import { coercedPositiveIntSchema, requiredStringSchema } from '../utils/zod.util';

const portSchema = coercedPositiveIntSchema.max(65535);

const proxyHeadersSchema = parseJsonEnvironmentVariable('PROXY_HEADERS').pipe(
  z.record(z.string()),
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

export const ProxyConfigSchema = z.discriminatedUnion('authMode', [
  z.object({
    authMode: z.literal('none').describe('Proxy disabled'),
  }),
  z.object({
    authMode: z.literal('basic').describe('Basic authentication'),
    ...baseProxyFields,
    username: requiredStringSchema.describe('Proxy username'),
    password: requiredStringSchema.describe('Proxy password'),
  }),
  z.object({
    authMode: z.literal('tls').describe('TLS client certificate authentication'),
    ...baseProxyFields,
    tlsCertPath: requiredStringSchema.describe('Path to TLS client certificate'),
    tlsKeyPath: requiredStringSchema.describe('Path to TLS client key'),
  }),
]);

export type ProxyConfig = z.infer<typeof ProxyConfigSchema>;
export type NoneProxyConfig = Extract<ProxyConfig, { authMode: 'none' }>;
export type BasicProxyConfig = Extract<ProxyConfig, { authMode: 'basic' }>;
export type TlsProxyConfig = Extract<ProxyConfig, { authMode: 'tls' }>;

export const proxyConfig = registerConfig('proxy', ProxyConfigSchema, {
  whitelistKeys: new Set([
    'PROXY_AUTH_MODE',
    'PROXY_HOST',
    'PROXY_PORT',
    'PROXY_PROTOCOL',
    'PROXY_USERNAME',
    'PROXY_PASSWORD',
    'PROXY_TLS_CERT_PATH',
    'PROXY_TLS_KEY_PATH',
    'PROXY_CA_BUNDLE_PATH',
    'PROXY_HEADERS',
  ]),
});

export type ProxyConfigType = ConfigType<typeof proxyConfig>;
export type ProxyConfigNamespaced = NamespacedConfigType<typeof proxyConfig>;
```

**Step 2: Export from config index**

Add to `services/sharepoint-connector/src/config/index.ts`:

```typescript
export * from './proxy.schema';
```

Also add `proxyConfig` to the `Config` type and config array (check existing pattern in file).

**Step 3: Commit**

```bash
git add services/sharepoint-connector/src/config/proxy.schema.ts services/sharepoint-connector/src/config/index.ts
git commit -m "feat(sharepoint-connector): add proxy configuration schema"
```

---

## Task 2: Create ProxyService

**Files:**
- Create: `services/sharepoint-connector/src/proxy/proxy.service.ts`
- Create: `services/sharepoint-connector/src/proxy/proxy.module.ts`
- Create: `services/sharepoint-connector/src/proxy/index.ts`

**Step 1: Create proxy service**

```typescript
// services/sharepoint-connector/src/proxy/proxy.service.ts
import { readFileSync } from 'node:fs';
import { Injectable, Logger, OnModuleDestroy } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Agent, Dispatcher, ProxyAgent } from 'undici';
import { Config } from '../config';
import { BasicProxyConfig, ProxyConfig, TlsProxyConfig } from '../config/proxy.schema';

export type ProxyMode = 'always' | 'external-only';

@Injectable()
export class ProxyService implements OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private readonly dispatcher: Dispatcher;
  private readonly noProxyDispatcher: Dispatcher;
  private readonly isExternalMode: boolean;

  public constructor(private readonly configService: ConfigService<Config, true>) {
    const proxyConfig = this.configService.get('proxy', { infer: true });
    const uniqueConfig = this.configService.get('unique', { infer: true });

    this.isExternalMode = uniqueConfig.serviceAuthMode === 'external';
    this.noProxyDispatcher = new Agent();
    this.dispatcher = this.createDispatcher(proxyConfig);

    this.logger.log({
      msg: 'ProxyService initialized',
      authMode: proxyConfig.authMode,
      isExternalMode: this.isExternalMode,
    });
  }

  public getDispatcher(mode: ProxyMode = 'always'): Dispatcher {
    if (mode === 'external-only' && !this.isExternalMode) {
      return this.noProxyDispatcher;
    }
    return this.dispatcher;
  }

  public getProxyConfig(): ProxyConfig {
    return this.configService.get('proxy', { infer: true });
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
        `${proxyConfig.username}:${proxyConfig.password}`,
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

    if (proxyConfig.headers) {
      proxyOptions.headers = proxyConfig.headers;
    }

    this.logger.log({
      msg: 'Created ProxyAgent',
      proxyUrl,
      authMode: proxyConfig.authMode,
    });

    return new ProxyAgent(proxyOptions);
  }

  private buildProxyUrl(proxyConfig: BasicProxyConfig | TlsProxyConfig): string {
    return `${proxyConfig.protocol}://${proxyConfig.host}:${proxyConfig.port}`;
  }
}
```

**Step 2: Create proxy module**

```typescript
// services/sharepoint-connector/src/proxy/proxy.module.ts
import { Global, Module } from '@nestjs/common';
import { ProxyService } from './proxy.service';

@Global()
@Module({
  providers: [ProxyService],
  exports: [ProxyService],
})
export class ProxyModule {}
```

**Step 3: Create index export**

```typescript
// services/sharepoint-connector/src/proxy/index.ts
export * from './proxy.module';
export * from './proxy.service';
```

**Step 4: Commit**

```bash
git add services/sharepoint-connector/src/proxy/
git commit -m "feat(sharepoint-connector): add ProxyService"
```

---

## Task 3: Register ProxyModule in AppModule

**Files:**
- Modify: `services/sharepoint-connector/src/app.module.ts`

**Step 1: Import and register ProxyModule**

Add import:
```typescript
import { ProxyModule } from './proxy';
```

Add `ProxyModule` to the imports array (should be near the top, before modules that depend on it).

**Step 2: Commit**

```bash
git add services/sharepoint-connector/src/app.module.ts
git commit -m "feat(sharepoint-connector): register ProxyModule in AppModule"
```

---

## Task 4: Update HttpClientService

**Files:**
- Modify: `services/sharepoint-connector/src/shared/services/http-client.service.ts`

**Step 1: Inject ProxyService and use dispatcher**

Note: This service composes interceptors on top of the base dispatcher. The composed dispatcher should be closed in `onModuleDestroy` - this does NOT close the underlying ProxyService dispatcher.

```typescript
import { Injectable, OnModuleDestroy } from '@nestjs/common';
import { Dispatcher, interceptors } from 'undici';
import { ProxyService } from '../../proxy';

@Injectable()
export class HttpClientService implements OnModuleDestroy {
  private readonly httpAgent: Dispatcher;

  public constructor(private readonly proxyService: ProxyService) {
    const baseDispatcher = this.proxyService.getDispatcher('external-only');
    this.httpAgent = baseDispatcher.compose([interceptors.retry(), interceptors.redirect()]);
  }

  public async onModuleDestroy(): Promise<void> {
    // Close the composed dispatcher (not the underlying ProxyService dispatcher)
    await this.httpAgent.close();
  }

  public async request(
    url: string | URL,
    options?: Omit<Dispatcher.RequestOptions, 'origin' | 'path'>,
  ): Promise<Dispatcher.ResponseData> {
    const urlObj = typeof url === 'string' ? new URL(url) : url;
    return await this.httpAgent.request({
      origin: urlObj.origin,
      path: urlObj.pathname + urlObj.search,
      method: options?.method || 'GET',
      ...options,
    });
  }
}
```

**Step 2: Commit**

```bash
git add services/sharepoint-connector/src/shared/services/http-client.service.ts
git commit -m "feat(sharepoint-connector): use ProxyService in HttpClientService"
```

---

## Task 5: Update SharepointRestHttpService

**Files:**
- Modify: `services/sharepoint-connector/src/microsoft-apis/sharepoint-rest/sharepoint-rest-http.service.ts`

**Step 1: Inject ProxyService, store origin, use dispatcher**

Key changes:
1. Inject `ProxyService`
2. Store `origin` from config (previously bound to Client at construction)
3. Add `origin` to each `request()` call (Agent/ProxyAgent are multi-origin)
4. Keep `onModuleDestroy` - closes the composed dispatcher, not the underlying one

Add import:
```typescript
import { ProxyService } from '../../proxy';
```

Update class:

```typescript
@Injectable()
export class SharepointRestHttpService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly client: Dispatcher;
  private readonly origin: string;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
    private readonly configService: ConfigService<Config, true>,
    private readonly proxyService: ProxyService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
    this.origin = this.configService.get('sharepoint.baseUrl', { infer: true });

    const interceptorsInCallingOrder = [
      interceptors.redirect({
        maxRedirections: 10,
      }),
      interceptors.retry({
        maxRetries: 4,
        minTimeout: 3_000,
        methods: ['GET', 'POST'],
        errorCodes: [
          'ETIMEDOUT',
          'ECONNRESET',
          'ECONNREFUSED',
          'ENOTFOUND',
          'ENETDOWN',
          'ENETUNREACH',
          'EHOSTDOWN',
          'EHOSTUNREACH',
          'EPIPE',
          'UND_ERR_SOCKET',
        ],
      }),
      createTokenRefreshInterceptor(async () =>
        this.microsoftAuthenticationService.getAccessToken('sharepoint-rest'),
      ),
      createLoggingInterceptor(this.shouldConcealLogs),
    ];

    const baseDispatcher = this.proxyService.getDispatcher('always');
    this.client = baseDispatcher.compose(interceptorsInCallingOrder.reverse());
  }
```

Update `requestSingle` method - add origin:
```typescript
const { statusCode, body } = await this.client.request({
  origin: this.origin,
  method: 'GET',
  path,
  headers: { ... },
});
```

Update `requestBatch` method - add origin:
```typescript
const { statusCode, body, headers } = await this.client.request({
  origin: this.origin,
  method: 'POST',
  path,
  headers: { ... },
  body: requestBody,
});
```

Remove `Client` from undici import (keep `Dispatcher, interceptors`).

**Step 2: Commit**

```bash
git add services/sharepoint-connector/src/microsoft-apis/sharepoint-rest/sharepoint-rest-http.service.ts
git commit -m "feat(sharepoint-connector): use ProxyService in SharepointRestHttpService"
```

---

## Task 6: Update IngestionHttpClient

**Files:**
- Modify: `services/sharepoint-connector/src/unique-api/clients/ingestion-http.client.ts`

**Step 1: Inject ProxyService, store origin, use dispatcher**

Same pattern as SharepointRestHttpService:
1. Inject `ProxyService`
2. Store `origin` from config
3. Add `origin` to each `request()` call

Add import:
```typescript
import { ProxyService } from '../../proxy';
```

Update constructor:

```typescript
public constructor(
  private readonly uniqueAuthService: UniqueAuthService,
  private readonly configService: ConfigService<Config, true>,
  private readonly bottleneckFactory: BottleneckFactory,
  private readonly proxyService: ProxyService,
  @Inject(SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS)
  private readonly spcUniqueApiRequestDurationSeconds: Histogram,
  @Inject(SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL)
  private readonly spcUniqueApiSlowRequestsTotal: Counter,
) {
  const ingestionUrl = new URL(
    this.configService.get('unique.ingestionServiceBaseUrl', { infer: true }),
  );
  this.origin = `${ingestionUrl.protocol}//${ingestionUrl.host}`;

  const interceptorsInCallingOrder = [
    interceptors.redirect({
      maxRedirections: 10,
    }),
    interceptors.retry({
      maxRetries: 3,
      minTimeout: 3_000,
      methods: ['POST'],
      throwOnError: false,
    }),
  ];

  const baseDispatcher = this.proxyService.getDispatcher('external-only');
  this.httpClient = baseDispatcher.compose(interceptorsInCallingOrder.reverse());

  // ... rest of constructor unchanged
}
```

Add `origin` field:
```typescript
private readonly origin: string;
```

Update `request` method - add origin:
```typescript
const result = await this.httpClient.request({
  origin: this.origin,
  ...options,
  headers: {
    ...options.headers,
    ...(await this.getHeaders()),
  },
});
```

Remove `Client` from undici import (keep `Dispatcher, errors, interceptors`).

**Step 2: Commit**

```bash
git add services/sharepoint-connector/src/unique-api/clients/ingestion-http.client.ts
git commit -m "feat(sharepoint-connector): use ProxyService in IngestionHttpClient"
```

---

## Task 7: Update UniqueGraphqlClient

**Files:**
- Modify: `services/sharepoint-connector/src/unique-api/clients/unique-graphql.client.ts`
- Modify: `services/sharepoint-connector/src/unique-api/unique-api.module.ts`

**Step 1: Add custom fetch with proxy dispatcher**

Add import at top:
```typescript
import { fetch as undiciFetch } from 'undici';
import { ProxyService } from '../../proxy';
```

Update constructor signature to accept ProxyService:
```typescript
public constructor(
  private readonly clientTarget: UniqueGraphqlClientTarget,
  private readonly uniqueAuthService: UniqueAuthService,
  private readonly configService: ConfigService<Config, true>,
  private readonly bottleneckFactory: BottleneckFactory,
  private readonly proxyService: ProxyService,
  private readonly spcUniqueApiRequestDurationSeconds: Histogram,
  private readonly spcUniqueApiSlowRequestsTotal: Counter,
) {
```

Update GraphQLClient instantiation to use custom fetch:
```typescript
const dispatcher = this.proxyService.getDispatcher('external-only');

this.graphQlClient = new GraphQLClient(graphqlUrl, {
  fetch: (url, options) =>
    undiciFetch(url, {
      ...options,
      dispatcher,
    }),
  requestMiddleware: async (request) => {
    // ... existing middleware unchanged
  },
});
```

**Step 2: Update factory provider in unique-api.module.ts**

Find where `INGESTION_CLIENT` and `SCOPE_MANAGEMENT_CLIENT` are provided. Add `ProxyService` to the inject array and pass it to the constructor.

Example:
```typescript
{
  provide: INGESTION_CLIENT,
  useFactory: (
    uniqueAuthService: UniqueAuthService,
    configService: ConfigService<Config, true>,
    bottleneckFactory: BottleneckFactory,
    proxyService: ProxyService,
    spcUniqueApiRequestDurationSeconds: Histogram,
    spcUniqueApiSlowRequestsTotal: Counter,
  ) =>
    new UniqueGraphqlClient(
      'ingestion',
      uniqueAuthService,
      configService,
      bottleneckFactory,
      proxyService,
      spcUniqueApiRequestDurationSeconds,
      spcUniqueApiSlowRequestsTotal,
    ),
  inject: [
    UniqueAuthService,
    ConfigService,
    BottleneckFactory,
    ProxyService,
    SPC_UNIQUE_API_REQUEST_DURATION_SECONDS,
    SPC_UNIQUE_API_SLOW_REQUESTS_TOTAL,
  ],
},
```

**Step 3: Commit**

```bash
git add services/sharepoint-connector/src/unique-api/clients/unique-graphql.client.ts services/sharepoint-connector/src/unique-api/unique-api.module.ts
git commit -m "feat(sharepoint-connector): use ProxyService in UniqueGraphqlClient"
```

---

## Task 8: Update GraphClientFactory

**Files:**
- Modify: `services/sharepoint-connector/src/microsoft-apis/graph/graph-client.factory.ts`

**Step 1: Inject ProxyService and pass fetchOptions**

Add import:
```typescript
import { ProxyService } from '../../proxy';
```

Update constructor to inject ProxyService:
```typescript
public constructor(
  private readonly graphAuthenticationService: GraphAuthenticationService,
  private readonly configService: ConfigService<Config, true>,
  private readonly proxyService: ProxyService,
  @Inject(SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS)
  private readonly spcGraphApiRequestDurationSeconds: Histogram,
  // ... rest unchanged
) {}
```

Update `createClient` method to pass fetchOptions:
```typescript
const clientOptions: ClientOptions = {
  middleware: middlewares[0],
  debugLogging: false,
  fetchOptions: {
    dispatcher: this.proxyService.getDispatcher('always'),
  },
};
```

**Step 2: Commit**

```bash
git add services/sharepoint-connector/src/microsoft-apis/graph/graph-client.factory.ts
git commit -m "feat(sharepoint-connector): use ProxyService in GraphClientFactory"
```

---

## Task 9: Update Microsoft Auth Strategies (MSAL)

**Files:**
- Create: `services/sharepoint-connector/src/microsoft-apis/auth/msal-proxy-config.ts`
- Modify: `services/sharepoint-connector/src/microsoft-apis/auth/microsoft-authentication.service.ts`
- Modify: `services/sharepoint-connector/src/microsoft-apis/auth/strategies/certificate-auth.strategy.ts`
- Modify: `services/sharepoint-connector/src/microsoft-apis/auth/strategies/client-secret-auth.strategy.ts`

MSAL supports custom network client via `system.networkClient` configuration.

**Step 1: Create MSAL network client helper**

```typescript
// services/sharepoint-connector/src/microsoft-apis/auth/msal-proxy-config.ts
import { INetworkModule, NetworkRequestOptions, NetworkResponse } from '@azure/msal-node';
import { Dispatcher, fetch as undiciFetch } from 'undici';

export class ProxiedMsalNetworkClient implements INetworkModule {
  public constructor(private readonly dispatcher: Dispatcher) {}

  public async sendGetRequestAsync<T>(
    url: string,
    options?: NetworkRequestOptions,
  ): Promise<NetworkResponse<T>> {
    const response = await undiciFetch(url, {
      method: 'GET',
      headers: options?.headers as Record<string, string>,
      dispatcher: this.dispatcher,
    });

    return {
      headers: Object.fromEntries(response.headers.entries()),
      body: (await response.json()) as T,
      status: response.status,
    };
  }

  public async sendPostRequestAsync<T>(
    url: string,
    options?: NetworkRequestOptions,
  ): Promise<NetworkResponse<T>> {
    const response = await undiciFetch(url, {
      method: 'POST',
      headers: options?.headers as Record<string, string>,
      body: options?.body,
      dispatcher: this.dispatcher,
    });

    return {
      headers: Object.fromEntries(response.headers.entries()),
      body: (await response.json()) as T,
      status: response.status,
    };
  }
}
```

**Step 2: Update MicrosoftAuthenticationService**

The strategies are instantiated directly, not via DI. Pass dispatcher through.

Add import:
```typescript
import { ProxyService } from '../../proxy';
```

Update constructor:
```typescript
public constructor(
  private readonly configService: ConfigService<Config, true>,
  private readonly proxyService: ProxyService,
) {
  // ...
  const dispatcher = this.proxyService.getDispatcher('always');

  switch (authMode) {
    case 'client-secret':
      this.strategy = new ClientSecretAuthStrategy(configService, dispatcher);
      break;
    case 'certificate':
      this.strategy = new CertificateAuthStrategy(configService, dispatcher);
      break;
  }
}
```

**Step 3: Update CertificateAuthStrategy**

Add imports:
```typescript
import { Dispatcher } from 'undici';
import { ProxiedMsalNetworkClient } from '../msal-proxy-config';
```

Update constructor:
```typescript
public constructor(
  private readonly configService: ConfigService<Config, true>,
  private readonly dispatcher: Dispatcher,
) {
  // ... existing config code ...

  const msalConfig: Configuration = {
    auth: {
      clientId,
      authority: `https://login.microsoftonline.com/${tenantId}`,
      clientCertificate: {
        privateKey,
        ...(thumbprintSha256 ? { thumbprintSha256 } : { thumbprint }),
      },
    },
    system: {
      networkClient: new ProxiedMsalNetworkClient(this.dispatcher),
    },
  };

  this.msalClient = new ConfidentialClientApplication(msalConfig);
}
```

**Step 4: Update ClientSecretAuthStrategy similarly**

Same pattern - add dispatcher parameter and configure MSAL with ProxiedMsalNetworkClient.

**Step 5: Commit**

```bash
git add services/sharepoint-connector/src/microsoft-apis/auth/
git commit -m "feat(sharepoint-connector): use ProxyService in MSAL auth strategies"
```

---

## Task 10: Update Helm Chart - values.yaml

**Files:**
- Modify: `services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/values.yaml`

**Step 1: Add proxy configuration section**

Add after `processing` section (inside `connectorConfig`):

```yaml
# -- HTTP proxy configuration for external API calls
# Required for environments where internet access is only available through a proxy
proxy:
  # -- Proxy authentication mode
  # none: proxy disabled
  # basic: username/password authentication
  # tls: TLS client certificate authentication
  authMode: none
  # -- Proxy server hostname (required for basic/tls modes)
  # host: proxy.example.com
  # -- Proxy server port (required for basic/tls modes)
  # port: 8080
  # -- Proxy protocol: http or https (required for basic/tls modes)
  # protocol: http
  # -- Basic auth username (required for basic mode)
  # username: ""
  # -- Path to TLS client certificate (required for tls mode)
  # tlsCertPath: /app/proxy-certs/client.crt
  # -- Path to TLS client key (required for tls mode)
  # tlsKeyPath: /app/proxy-certs/client.key
  # -- Path to CA bundle for verifying proxy server certificate (optional)
  # caBundlePath: /app/proxy-certs/ca.crt
  # -- Optional JSON string of headers for CONNECT
  # headers: '{"X-Proxy-Header":"value"}'
```

**Step 2: Commit**

```bash
git add services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/values.yaml
git commit -m "feat(sharepoint-connector): add proxy config to Helm values"
```

---

## Task 11: Create Helm Chart - proxy ConfigMap template

**Files:**
- Create: `services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/templates/proxy-configmap.yaml`

**Step 1: Create ConfigMap template**

Note: No `required` helpers - validation happens at app startup.

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sharepoint-connector-proxy-config
  labels:
    {{- include "chart.labels" . | nindent 4 }}
data:
  PROXY_AUTH_MODE: {{ .Values.connectorConfig.proxy.authMode | quote }}
  {{- if ne .Values.connectorConfig.proxy.authMode "none" }}
  PROXY_HOST: {{ .Values.connectorConfig.proxy.host | quote }}
  PROXY_PORT: {{ .Values.connectorConfig.proxy.port | quote }}
  PROXY_PROTOCOL: {{ .Values.connectorConfig.proxy.protocol | quote }}
  {{- end }}
  {{- if eq .Values.connectorConfig.proxy.authMode "basic" }}
  PROXY_USERNAME: {{ .Values.connectorConfig.proxy.username | quote }}
  {{- end }}
  {{- if eq .Values.connectorConfig.proxy.authMode "tls" }}
  PROXY_TLS_CERT_PATH: {{ .Values.connectorConfig.proxy.tlsCertPath | quote }}
  PROXY_TLS_KEY_PATH: {{ .Values.connectorConfig.proxy.tlsKeyPath | quote }}
  {{- end }}
  {{- if .Values.connectorConfig.proxy.caBundlePath }}
  PROXY_CA_BUNDLE_PATH: {{ .Values.connectorConfig.proxy.caBundlePath | quote }}
  {{- end }}
```

Note: `PROXY_PASSWORD` must come from a Secret via `connector.envVars` (do not include in ConfigMap).

**Step 2: Commit**

```bash
git add services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/templates/proxy-configmap.yaml
git commit -m "feat(sharepoint-connector): add proxy ConfigMap template"
```

---

## Task 12: Update Helm Chart - reference ConfigMap in deployment

**Files:**
- Check: `services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/templates/` for deployment template or helpers

**Step 1: Add extraEnvCM reference**

Find how existing ConfigMaps are referenced. Add `sharepoint-connector-proxy-config` to the list of ConfigMaps loaded as environment variables.

Also ensure `connector.envVars` supports adding `PROXY_PASSWORD` from a Secret for `authMode: basic`.

This may involve:
- Updating `connector.extraEnvCM` default value
- Or modifying the deployment template to always include the proxy ConfigMap

**Step 2: Commit**

```bash
git add services/sharepoint-connector/deploy/helm-charts/sharepoint-connector/templates/
git commit -m "feat(sharepoint-connector): reference proxy ConfigMap in deployment"
```

---

## Task 13: Fix Existing Tests

**Files:**
- Various test files that test services now requiring ProxyService

**Step 1: Identify failing tests**

Run: `pnpm test --filter=@unique-ag/sharepoint-connector`

**Step 2: Mock ProxyService in affected tests**

For each failing test, add ProxyService mock:

```typescript
import { Agent } from 'undici';

// In test setup
const mockProxyService = {
  getDispatcher: vi.fn().mockReturnValue(new Agent()),
  getProxyConfig: vi.fn().mockReturnValue({ authMode: 'none' }),
};

// In TestBed setup
.mock(ProxyService)
.impl(() => mockProxyService)
```

**Step 3: Commit**

```bash
git add services/sharepoint-connector/src/**/*.spec.ts
git commit -m "test(sharepoint-connector): mock ProxyService in existing tests"
```

---

## Task 14: Final Verification

**Step 1: Run all checks**

```bash
pnpm check-types
pnpm style
pnpm test --filter=@unique-ag/sharepoint-connector
```

**Step 2: Fix any remaining issues**

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "fix(sharepoint-connector): address review feedback"
```

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Add proxy configuration schema |
| 2 | Create ProxyService |
| 3 | Register ProxyModule in AppModule |
| 4 | Update HttpClientService |
| 5 | Update SharepointRestHttpService (add origin to requests) |
| 6 | Update IngestionHttpClient (add origin to requests) |
| 7 | Update UniqueGraphqlClient |
| 8 | Update GraphClientFactory |
| 9 | Update MSAL auth strategies (custom network client) |
| 10 | Update Helm values.yaml |
| 11 | Create proxy ConfigMap template (no required helpers) |
| 12 | Reference ConfigMap in deployment |
| 13 | Fix existing tests |
| 14 | Final verification |
