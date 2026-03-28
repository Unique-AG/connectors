import { NodeHttpClient } from '@effect/platform-node';
import {
  Cause,
  Clock,
  Duration,
  Effect,
  Fiber,
  Layer,
  Option,
  Ref,
  Result,
  Schedule,
  Schema,
} from 'effect';
import { HttpClient, HttpClientRequest } from 'effect/unstable/http';
import { AuthenticationFailedError, TokenExpiredError } from '../Errors/errors';
import type { AccessTokenInfo, AccountInfo, MsGraphAuthInterface } from './MsGraphAuth';
import { DelegatedAuth } from './MsGraphAuth';
import { DelegatedAuthConfig } from './MsGraphAuthConfig';
import {
  type AccountCacheEntry,
  emptyTokenCacheState,
  isTokenExpired,
  makeScopesKey,
  makeTokenCacheContext,
  REFRESH_BUFFER_MS,
  type TokenCacheState,
} from './TokenCache';

const OAuthTokenResponseSchema = Schema.Struct({
  access_token: Schema.String,
  token_type: Schema.String,
  expires_in: Schema.Number,
  scope: Schema.String,
  refresh_token: Schema.optionalKey(Schema.String),
  id_token: Schema.optionalKey(Schema.String),
});

const OAuthErrorResponseSchema = Schema.Struct({
  error: Schema.String,
  error_description: Schema.optionalKey(Schema.String),
});

const DeviceCodeResponseSchema = Schema.Struct({
  device_code: Schema.String,
  user_code: Schema.String,
  verification_uri: Schema.String,
  expires_in: Schema.Number,
  interval: Schema.Number,
  message: Schema.String,
});

type OAuthTokenResponse = typeof OAuthTokenResponseSchema.Type;
type DeviceCodeResponse = typeof DeviceCodeResponseSchema.Type;

// Sentinel error used only inside pollDeviceCodeToken to trigger retry
class PendingPollError {
  public readonly _tag = 'PendingPollError' as const;
}

const parseTokenResponse = Effect.fn('DelegatedAuth.parseTokenResponse')(
  function* (
    raw: OAuthTokenResponse,
    existingAccountId?: string,
  ): Effect.fn.Return<AccessTokenInfo, never> {
    const nowMs = yield* Clock.currentTimeMillis;
    const expiresOn = new Date(nowMs + raw.expires_in * 1000);
    return {
      accessToken: raw.access_token,
      expiresOn,
      scopes: raw.scope.split(' '),
      account: existingAccountId
        ? ({
            homeAccountId: existingAccountId,
            localAccountId: existingAccountId,
            username: '',
            tenantId: '',
            name: null,
          } satisfies AccountInfo)
        : null,
      tokenType: 'Bearer',
    };
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'parseTokenResponse' }),
);

const extractAccountFromJwt = Effect.fn('DelegatedAuth.extractAccountFromJwt')(
  function* (idToken: string): Effect.fn.Return<AccountCacheEntry | null, never> {
    const parts = idToken.split('.');
    if (parts.length < 2) {
      return null as AccountCacheEntry | null;
    }
    return yield* Effect.try({
      try: () => {
        const payload = JSON.parse(Buffer.from(parts[1] ?? '', 'base64url').toString('utf-8')) as {
          sub?: string;
          oid?: string;
          preferred_username?: string;
          tid?: string;
          name?: string;
        };
        return {
          homeAccountId: `${payload.oid ?? payload.sub ?? 'unknown'}.${payload.tid ?? ''}`,
          localAccountId: payload.oid ?? payload.sub ?? 'unknown',
          username: payload.preferred_username ?? '',
          tenantId: payload.tid ?? '',
          name: payload.name ?? null,
        } as AccountCacheEntry;
      },
      catch: (_e) => _e,
    }).pipe(Effect.orElseSucceed(() => null as AccountCacheEntry | null));
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'extractAccountFromJwt' }),
);

const postForm = Effect.fn('DelegatedAuth.postForm')(
  function* (
    url: string,
    params: Record<string, string>,
  ): Effect.fn.Return<unknown, AuthenticationFailedError> {
    return yield* HttpClientRequest.post(url).pipe(
      HttpClientRequest.bodyUrlParams(params),
      HttpClient.execute,
      Effect.flatMap((resp) => resp.json),
      Effect.scoped,
      Effect.timeout('10 seconds'),
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: 'unknown',
            message: Cause.isTimeoutError(e)
              ? `Token request timed out after 10 seconds`
              : `Token request failed: ${String(e)}`,
            correlationId: undefined,
          }),
      ),
      Effect.provide(NodeHttpClient.layerUndici),
    );
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'postForm' }),
);

const parseTokenJson = Effect.fn('DelegatedAuth.parseTokenJson')(
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
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'parseTokenJson' }),
);

const parseDeviceCodeJson = Effect.fn('DelegatedAuth.parseDeviceCodeJson')(
  function* (json: unknown): Effect.fn.Return<DeviceCodeResponse, AuthenticationFailedError> {
    return yield* Schema.decodeUnknownEffect(DeviceCodeResponseSchema)(json).pipe(
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: 'unknown',
            message: `Unexpected device code response shape: ${e.message}`,
            correlationId: undefined,
          }),
      ),
    );
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'parseDeviceCodeJson' }),
);

const acquireSilent = Effect.fn('DelegatedAuth.acquireSilent')(
  function* (
    stateRef: Ref.Ref<TokenCacheState>,
    config: DelegatedAuthConfig['Service'],
    tokenEndpoint: string,
  ): Effect.fn.Return<AccessTokenInfo, AuthenticationFailedError | TokenExpiredError> {
    const state = yield* Ref.get(stateRef);
    const scopesKey = makeScopesKey('any', config.scopes);

    const cachedEntry = state.tokens.get(scopesKey);
    if (cachedEntry && !isTokenExpired(cachedEntry.expiresOn, REFRESH_BUFFER_MS)) {
      const account = state.accounts.get(cachedEntry.accountId) ?? null;
      return {
        accessToken: cachedEntry.accessToken,
        expiresOn: cachedEntry.expiresOn,
        scopes: cachedEntry.scopes,
        account: account
          ? ({
              homeAccountId: account.homeAccountId,
              localAccountId: account.localAccountId,
              username: account.username,
              tenantId: account.tenantId,
              name: account.name,
            } satisfies AccountInfo)
          : null,
        tokenType: 'Bearer' as const,
      } satisfies AccessTokenInfo;
    }

    if (cachedEntry) {
      yield* Option.match(cachedEntry.refreshToken, {
        onNone: () => Effect.void,
        onSome: (refreshToken) =>
          Effect.gen(function* () {
            const params: Record<string, string> = {
              client_id: config.clientId,
              grant_type: 'refresh_token',
              refresh_token: refreshToken,
              scope: config.scopes.join(' '),
            };
            if (config.clientSecret) {
              params.client_secret = config.clientSecret;
            }

            const json = yield* postForm(tokenEndpoint, params);
            const raw = yield* parseTokenJson(json);
            const tokenInfo = yield* parseTokenResponse(raw, cachedEntry.accountId);

            yield* Ref.update(stateRef, (s) => {
              const newTokens = new Map(s.tokens);
              newTokens.set(scopesKey, {
                accessToken: tokenInfo.accessToken,
                expiresOn: tokenInfo.expiresOn,
                scopes: [...tokenInfo.scopes],
                refreshToken: raw.refresh_token ? Option.some(raw.refresh_token) : Option.none(),
                accountId: cachedEntry.accountId,
              });
              return { ...s, tokens: newTokens };
            });

            return tokenInfo;
          }),
      });

      // If refresh token was present and successful, re-read the updated cache
      const updatedState = yield* Ref.get(stateRef);
      const updatedEntry = updatedState.tokens.get(scopesKey);
      if (updatedEntry && !isTokenExpired(updatedEntry.expiresOn, REFRESH_BUFFER_MS)) {
        const account = updatedState.accounts.get(updatedEntry.accountId) ?? null;
        return {
          accessToken: updatedEntry.accessToken,
          expiresOn: updatedEntry.expiresOn,
          scopes: updatedEntry.scopes,
          account: account
            ? ({
                homeAccountId: account.homeAccountId,
                localAccountId: account.localAccountId,
                username: account.username,
                tenantId: account.tenantId,
                name: account.name,
              } satisfies AccountInfo)
            : null,
          tokenType: 'Bearer' as const,
        } satisfies AccessTokenInfo;
      }
    }

    const nowMs = yield* Clock.currentTimeMillis;
    return yield* Effect.fail(
      new TokenExpiredError({
        expiredAt: nowMs,
      }),
    );
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'acquireSilent' }),
);

// pollDeviceCodeOnce fails with PendingPollError when authorization_pending,
// fails with AuthenticationFailedError on fatal errors,
// and succeeds with OAuthTokenResponse on success.
const pollDeviceCodeOnce = Effect.fn('DelegatedAuth.pollDeviceCodeOnce')(
  function* (
    tokenEndpoint: string,
    clientId: string,
    deviceCode: string,
  ): Effect.fn.Return<OAuthTokenResponse, PendingPollError | AuthenticationFailedError> {
    const params: Record<string, string> = {
      client_id: clientId,
      grant_type: 'urn:ietf:params:oauth:grant-type:device_code',
      device_code: deviceCode,
    };

    const json = yield* postForm(tokenEndpoint, params);
    const shaped = json as Record<string, unknown>;

    if ('error' in shaped && shaped.error === 'authorization_pending') {
      return yield* Effect.fail(new PendingPollError());
    }

    if ('error' in shaped) {
      const errMsg =
        'error_description' in shaped ? String(shaped.error_description) : String(shaped.error);
      return yield* Effect.fail(
        new AuthenticationFailedError({
          reason: 'unknown',
          message: `Device code poll failed: ${errMsg}`,
          correlationId: undefined,
        }),
      );
    }

    return yield* parseTokenJson(json);
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'pollDeviceCodeOnce' }),
);

const pollDeviceCodeTokenLoop = Effect.fn('DelegatedAuth.pollDeviceCodeTokenLoop')(
  function* (
    tokenEndpoint: string,
    clientId: string,
    deviceCode: string,
    pollInterval: Duration.Duration,
  ): Effect.fn.Return<OAuthTokenResponse, AuthenticationFailedError> {
    const deviceCodeSchedule = Schedule.fixed(pollInterval).pipe(
      Schedule.andThen(Schedule.during('15 minutes')),
    );

    return yield* pollDeviceCodeOnce(tokenEndpoint, clientId, deviceCode).pipe(
      Effect.retry({
        schedule: deviceCodeSchedule,
        while: (e) => e._tag === 'PendingPollError',
      }),
      Effect.catchTag('PendingPollError', () =>
        Effect.fail(
          new AuthenticationFailedError({
            reason: 'unknown',
            message: 'Device code authorization timed out after 15 minutes',
            correlationId: undefined,
          }),
        ),
      ),
    );
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'pollDeviceCodeTokenLoop' }),
);

const acquireByCode = Effect.fn('DelegatedAuth.acquireByCode')(
  function* (
    stateRef: Ref.Ref<TokenCacheState>,
    config: DelegatedAuthConfig['Service'],
    tokenEndpoint: string,
    authorizationCode: string,
  ): Effect.fn.Return<AccessTokenInfo, AuthenticationFailedError> {
    const params: Record<string, string> = {
      client_id: config.clientId,
      grant_type: 'authorization_code',
      code: authorizationCode,
      redirect_uri: config.redirectUri,
      scope: config.scopes.join(' '),
    };
    if (config.clientSecret) {
      params.client_secret = config.clientSecret;
    }

    const json = yield* postForm(tokenEndpoint, params);
    const raw = yield* parseTokenJson(json);
    const account = raw.id_token ? yield* extractAccountFromJwt(raw.id_token) : null;
    const nowMs = yield* Clock.currentTimeMillis;
    const accountId = account?.homeAccountId ?? `unknown-${nowMs}`;
    const tokenInfo = yield* parseTokenResponse(raw, accountId);
    const scopesKey = makeScopesKey(accountId, config.scopes);

    yield* Ref.update(stateRef, (s) => {
      const newTokens = new Map(s.tokens);
      const newAccounts = new Map(s.accounts);
      newTokens.set(scopesKey, {
        accessToken: tokenInfo.accessToken,
        expiresOn: tokenInfo.expiresOn,
        scopes: [...tokenInfo.scopes],
        refreshToken: raw.refresh_token ? Option.some(raw.refresh_token) : Option.none(),
        accountId,
      });
      if (account) {
        newAccounts.set(accountId, account);
      }
      return { tokens: newTokens, accounts: newAccounts };
    });

    if (config.cachePlugin) {
      const ctx = makeTokenCacheContext(stateRef);
      yield* config.cachePlugin.afterCacheAccess(ctx);
    }

    return tokenInfo;
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'acquireByCode' }),
);

const acquireByDeviceCode = Effect.fn('DelegatedAuth.acquireByDeviceCode')(
  function* (
    stateRef: Ref.Ref<TokenCacheState>,
    config: DelegatedAuthConfig['Service'],
    tokenEndpoint: string,
  ): Effect.fn.Return<
    { tokenInfo: AccessTokenInfo; deviceCodeMessage: string },
    AuthenticationFailedError
  > {
    const deviceCodeEndpoint = tokenEndpoint.replace('/token', '/devicecode');

    const deviceCodeParams: Record<string, string> = {
      client_id: config.clientId,
      scope: config.scopes.join(' '),
    };

    const deviceCodeJson = yield* postForm(deviceCodeEndpoint, deviceCodeParams);
    const deviceCodeRaw = yield* parseDeviceCodeJson(deviceCodeJson);

    const pollInterval = Duration.millis(deviceCodeRaw.interval * 1000);
    const raw = yield* pollDeviceCodeTokenLoop(
      tokenEndpoint,
      config.clientId,
      deviceCodeRaw.device_code,
      pollInterval,
    );

    const account = raw.id_token ? yield* extractAccountFromJwt(raw.id_token) : null;
    const nowMs = yield* Clock.currentTimeMillis;
    const accountId = account?.homeAccountId ?? `unknown-${nowMs}`;
    const tokenInfo = yield* parseTokenResponse(raw, accountId);
    const scopesKey = makeScopesKey(accountId, config.scopes);

    yield* Ref.update(stateRef, (s) => {
      const newTokens = new Map(s.tokens);
      const newAccounts = new Map(s.accounts);
      newTokens.set(scopesKey, {
        accessToken: tokenInfo.accessToken,
        expiresOn: tokenInfo.expiresOn,
        scopes: [...tokenInfo.scopes],
        refreshToken: raw.refresh_token ? Option.some(raw.refresh_token) : Option.none(),
        accountId,
      });
      if (account) {
        newAccounts.set(accountId, account);
      }
      return { tokens: newTokens, accounts: newAccounts };
    });

    return { tokenInfo, deviceCodeMessage: deviceCodeRaw.message };
  },
  Effect.annotateLogs({ service: 'DelegatedAuth', method: 'acquireByDeviceCode' }),
);

const proactiveRefreshFiber = (
  stateRef: Ref.Ref<TokenCacheState>,
  config: DelegatedAuthConfig['Service'],
  tokenEndpoint: string,
) =>
  Effect.gen(function* () {
    const state = yield* Ref.get(stateRef);
    const now = yield* Clock.currentTimeMillis;

    for (const [key, entry] of state.tokens) {
      const msUntilExpiry = entry.expiresOn.getTime() - now;
      if (msUntilExpiry > 0 && msUntilExpiry <= REFRESH_BUFFER_MS) {
        yield* Option.match(entry.refreshToken, {
          onNone: () => Effect.void,
          onSome: (refreshToken) =>
            Effect.gen(function* () {
              const params: Record<string, string> = {
                client_id: config.clientId,
                grant_type: 'refresh_token',
                refresh_token: refreshToken,
                scope: config.scopes.join(' '),
              };
              if (config.clientSecret) {
                params.client_secret = config.clientSecret;
              }

              const refreshed = yield* postForm(tokenEndpoint, params).pipe(
                Effect.flatMap(parseTokenJson),
                Effect.option,
              );

              yield* Option.match(refreshed, {
                onNone: () => Effect.void,
                onSome: (token) =>
                  Effect.gen(function* () {
                    const nowMs = yield* Clock.currentTimeMillis;
                    yield* Ref.update(stateRef, (s) => {
                      const newTokens = new Map(s.tokens);
                      newTokens.set(key, {
                        accessToken: token.access_token,
                        expiresOn: new Date(nowMs + token.expires_in * 1000),
                        scopes: token.scope.split(' '),
                        refreshToken: token.refresh_token
                          ? Option.some(token.refresh_token)
                          : entry.refreshToken,
                        accountId: entry.accountId,
                      });
                      return { ...s, tokens: newTokens };
                    });
                    if (config.cachePlugin) {
                      yield* config.cachePlugin.afterCacheAccess(makeTokenCacheContext(stateRef));
                    }
                  }),
              });
            }),
        });
      }
    }
  }).pipe(Effect.repeat(Schedule.spaced(Duration.minutes(1))), Effect.ignore);

const makeService = (
  config: DelegatedAuthConfig['Service'],
  stateRef: Ref.Ref<TokenCacheState>,
): MsGraphAuthInterface => {
  const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`;

  return {
    grantedScopes: config.scopes,

    acquireToken: acquireSilent(stateRef, config, tokenEndpoint),

    getCachedAccounts: Effect.map(Ref.get(stateRef), (state) =>
      [...state.accounts.values()].map(
        (a) =>
          ({
            homeAccountId: a.homeAccountId,
            localAccountId: a.localAccountId,
            username: a.username,
            tenantId: a.tenantId,
            name: a.name,
          }) satisfies AccountInfo,
      ),
    ),

    removeCachedAccount: (accountId: string) =>
      Ref.update(stateRef, (s) => {
        const newAccounts = new Map(s.accounts);
        newAccounts.delete(accountId);
        const newTokens = new Map(
          [...s.tokens.entries()].filter(([, v]) => v.accountId !== accountId),
        );
        return { tokens: newTokens, accounts: newAccounts };
      }),
  };
};

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const DelegatedAuthLive = <_P extends string = string>() =>
  Layer.effect(
    DelegatedAuth,
    Effect.gen(function* () {
      const config = yield* DelegatedAuthConfig;
      const stateRef = yield* Ref.make<TokenCacheState>(emptyTokenCacheState);

      if (config.cachePlugin) {
        const ctx = makeTokenCacheContext(stateRef);
        yield* config.cachePlugin.beforeCacheAccess(ctx);
      }

      const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`;
      const refreshFiber = yield* Effect.forkScoped(
        proactiveRefreshFiber(stateRef, config, tokenEndpoint),
      );

      yield* Effect.addFinalizer(() => Fiber.interrupt(refreshFiber));

      return DelegatedAuth.of(makeService(config, stateRef));
    }).pipe(Effect.withSpan('DelegatedAuthLive.initialize')),
  );

// Suppress unused variable warnings for internal helpers used in tests or extended flows
void acquireByCode;
void acquireByDeviceCode;
