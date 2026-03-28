import { createSign } from 'node:crypto';
import { NodeHttpClient } from '@effect/platform-node';
import { Clock, Effect, Layer, Option, Ref, Result, Schema } from 'effect';
import { HttpClient, HttpClientRequest } from 'effect/unstable/http';
import { AuthenticationFailedError } from '../Errors/errors';
import type { AccessTokenInfo, MsGraphAuthInterface } from './MsGraphAuth';
import { ApplicationAuth } from './MsGraphAuth';
import { ApplicationAuthConfig } from './MsGraphAuthConfig';
import {
  emptyTokenCacheState,
  isTokenExpired,
  makeTokenCacheContext,
  REFRESH_BUFFER_MS,
  type TokenCacheState,
} from './TokenCache';

const OAuthTokenResponseSchema = Schema.Struct({
  access_token: Schema.String,
  expires_in: Schema.Number,
  token_type: Schema.String,
  scope: Schema.optionalKey(Schema.String),
});

const OAuthErrorResponseSchema = Schema.Struct({
  error: Schema.String,
  error_description: Schema.optionalKey(Schema.String),
});

type OAuthTokenResponse = typeof OAuthTokenResponseSchema.Type;

const base64UrlEncode = (input: string | Buffer): string => {
  const buf = typeof input === 'string' ? Buffer.from(input) : input;
  return buf.toString('base64url');
};

const makeClientAssertion = (
  clientId: string,
  tokenEndpoint: string,
  thumbprint: string,
  privateKey: string,
  nowSeconds: number,
  x5c?: string,
): string => {
  const header = x5c
    ? { alg: 'RS256', typ: 'JWT', x5c: [x5c] }
    : {
        alg: 'RS256',
        typ: 'JWT',
        x5t: Buffer.from(thumbprint, 'hex').toString('base64url'),
      };

  const payload = {
    aud: tokenEndpoint,
    iss: clientId,
    sub: clientId,
    jti: base64UrlEncode(Buffer.from(Math.random().toString())),
    nbf: nowSeconds,
    exp: nowSeconds + 600,
  };

  const headerEncoded = base64UrlEncode(JSON.stringify(header));
  const payloadEncoded = base64UrlEncode(JSON.stringify(payload));
  const signingInput = `${headerEncoded}.${payloadEncoded}`;

  const signer = createSign('RSA-SHA256');
  signer.update(signingInput);
  const signature = signer.sign(privateKey, 'base64url');

  return `${signingInput}.${signature}`;
};

const buildTokenParams = Effect.fn('ApplicationAuth.buildTokenParams')(
  function* (
    config: ApplicationAuthConfig['Service'],
    tokenEndpoint: string,
  ): Effect.fn.Return<Record<string, string>, AuthenticationFailedError> {
    const base: Record<string, string> = {
      client_id: config.clientId,
      grant_type: 'client_credentials',
      scope: config.scopes.join(' '),
    };

    if (config.clientSecret) {
      return { ...base, client_secret: config.clientSecret };
    }

    if (config.clientCertificate) {
      const { thumbprint, privateKey, x5c } = config.clientCertificate;
      const nowMs = yield* Clock.currentTimeMillis;
      const nowSeconds = Math.floor(nowMs / 1000);
      return yield* Effect.try({
        try: () => ({
          ...base,
          client_assertion_type: 'urn:ietf:params:oauth:client-assertion-type:jwt-bearer',
          client_assertion: makeClientAssertion(
            config.clientId,
            tokenEndpoint,
            thumbprint,
            privateKey,
            nowSeconds,
            x5c,
          ),
        }),
        catch: (e) =>
          new AuthenticationFailedError({
            reason: 'unknown',
            message: `Failed to build client assertion: ${String(e)}`,
            correlationId: undefined,
          }),
      });
    }

    return yield* Effect.fail(
      new AuthenticationFailedError({
        reason: 'invalid_client',
        message: 'ApplicationAuthConfig requires either clientSecret or clientCertificate',
        correlationId: undefined,
      }),
    );
  },
  Effect.annotateLogs({ service: 'ApplicationAuth', method: 'buildTokenParams' }),
);

const parseTokenJson = Effect.fn('ApplicationAuth.parseTokenJson')(
  function* (json: unknown): Effect.fn.Return<OAuthTokenResponse, AuthenticationFailedError> {
    const errorCheck = Schema.decodeUnknownResult(OAuthErrorResponseSchema)(json);
    const errorDescription = Result.match(errorCheck, {
      onSuccess: (r) => r.error_description,
      onFailure: () => undefined,
    });
    if (errorDescription) {
      return yield* Effect.fail(
        new AuthenticationFailedError({
          reason: 'invalid_grant',
          message: `Token endpoint error: ${errorDescription}`,
          correlationId: undefined,
        }),
      );
    }

    return yield* Schema.decodeUnknownEffect(OAuthTokenResponseSchema)(json).pipe(
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: 'unknown',
            message: `Unexpected token response shape: ${e.message}`,
            correlationId: undefined,
          }),
      ),
    );
  },
  Effect.annotateLogs({ service: 'ApplicationAuth', method: 'parseTokenJson' }),
);

const acquireClientCredentials = Effect.fn('ApplicationAuth.acquireClientCredentials')(
  function* (
    config: ApplicationAuthConfig['Service'],
    tokenEndpoint: string,
  ): Effect.fn.Return<OAuthTokenResponse, AuthenticationFailedError> {
    const params = yield* buildTokenParams(config, tokenEndpoint);

    const json = yield* HttpClientRequest.post(tokenEndpoint).pipe(
      HttpClientRequest.bodyUrlParams(params),
      HttpClient.execute,
      Effect.flatMap((resp) => resp.json),
      Effect.scoped,
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: 'unknown',
            message: `Token request failed: ${String(e)}`,
            correlationId: undefined,
          }),
      ),
      Effect.timeoutOrElse({
        duration: '10 seconds',
        orElse: () =>
          Effect.fail(
            new AuthenticationFailedError({
              reason: 'unknown',
              message: 'Token acquisition timed out',
              correlationId: undefined,
            }),
          ),
      }),
      Effect.provide(NodeHttpClient.layerUndici),
    );

    return yield* parseTokenJson(json);
  },
  Effect.annotateLogs({ service: 'ApplicationAuth', method: 'acquireClientCredentials' }),
);

const acquireToken = Effect.fn('ApplicationAuth.acquireToken')(
  function* (
    config: ApplicationAuthConfig['Service'],
    cachedTokenRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
    cacheStateRef: Ref.Ref<TokenCacheState>,
    tokenEndpoint: string,
  ): Effect.fn.Return<AccessTokenInfo, AuthenticationFailedError> {
    const cached = yield* Ref.get(cachedTokenRef).pipe(
      Effect.map(Option.filter((token) => !isTokenExpired(token.expiresOn, REFRESH_BUFFER_MS))),
    );

    return yield* Option.match(cached, {
      onSome: (token) => Effect.succeed(token),
      onNone: () =>
        Effect.gen(function* () {
          const raw = yield* acquireClientCredentials(config, tokenEndpoint);
          const nowMs = yield* Clock.currentTimeMillis;
          const expiresOn = new Date(nowMs + raw.expires_in * 1000);
          const tokenInfo: AccessTokenInfo = {
            accessToken: raw.access_token,
            expiresOn,
            scopes: raw.scope ? raw.scope.split(' ') : config.scopes,
            account: null,
            tokenType: 'Bearer',
          };

          yield* Ref.set(cachedTokenRef, Option.some(tokenInfo));

          if (config.cachePlugin) {
            const plugin = config.cachePlugin;
            const ctx = makeTokenCacheContext(cacheStateRef);
            yield* plugin.afterCacheAccess(ctx);
          }

          return tokenInfo;
        }),
    });
  },
  Effect.annotateLogs({ service: 'ApplicationAuth', method: 'acquireToken' }),
);

const makeService = (
  config: ApplicationAuthConfig['Service'],
  cachedTokenRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
  cacheStateRef: Ref.Ref<TokenCacheState>,
): MsGraphAuthInterface => {
  const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`;

  return {
    grantedScopes: config.scopes,
    acquireToken: acquireToken(config, cachedTokenRef, cacheStateRef, tokenEndpoint),
    getCachedAccounts: Effect.succeed([]),
    removeCachedAccount: (_accountId: string) => Ref.set(cachedTokenRef, Option.none()),
  };
};

// Generic parameter _P is intentional type branding used by external callers (e.g. MsGraphClient)
export const ApplicationAuthLive = <_P extends string = string>() =>
  Layer.effect(
    ApplicationAuth,
    Effect.gen(function* () {
      const config = yield* ApplicationAuthConfig;
      const cachedTokenRef = yield* Ref.make<Option.Option<AccessTokenInfo>>(Option.none());
      const cacheStateRef = yield* Ref.make<TokenCacheState>(emptyTokenCacheState);

      if (config.cachePlugin) {
        const plugin = config.cachePlugin;
        const ctx = makeTokenCacheContext(cacheStateRef);
        yield* plugin.beforeCacheAccess(ctx);
      }

      return ApplicationAuth.of(makeService(config, cachedTokenRef, cacheStateRef));
    }).pipe(Effect.withSpan('ApplicationAuthLive.initialize')),
  );
