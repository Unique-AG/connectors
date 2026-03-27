import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import {
  Duration,
  Effect,
  Fiber,
  Layer,
  Option,
  Ref,
  Schedule,
  pipe,
} from "effect"
import {
  AuthenticationFailedError,
  TokenExpiredError,
} from "../Errors/errors"
import type { AccessTokenInfo, AccountInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { DelegatedAuth } from "./MsGraphAuth"
import { DelegatedAuthConfig } from "./MsGraphAuthConfig"
import {
  REFRESH_BUFFER_MS,
  emptyTokenCacheState,
  isTokenExpired,
  makeScopesKey,
  makeTokenCacheContext,
  type AccountCacheEntry,
  type TokenCacheState,
} from "./TokenCache"

interface OAuthTokenResponse {
  readonly access_token: string
  readonly token_type: string
  readonly expires_in: number
  readonly scope: string
  readonly refresh_token?: string
  readonly id_token?: string
}

interface OAuthErrorResponse {
  readonly error: string
  readonly error_description: string
}

interface DeviceCodeResponse {
  readonly device_code: string
  readonly user_code: string
  readonly verification_uri: string
  readonly expires_in: number
  readonly interval: number
  readonly message: string
}

const parseTokenResponse = (
  raw: OAuthTokenResponse,
  existingAccountId?: string,
): AccessTokenInfo => {
  const expiresOn = new Date(Date.now() + raw.expires_in * 1000)
  return {
    accessToken: raw.access_token,
    expiresOn,
    scopes: raw.scope.split(" "),
    account: existingAccountId
      ? ({
          homeAccountId: existingAccountId,
          localAccountId: existingAccountId,
          username: "",
          tenantId: "",
          name: null,
        } satisfies AccountInfo)
      : null,
    tokenType: "Bearer",
  }
}

const extractAccountFromJwt = (idToken: string): AccountCacheEntry | null => {
  const parts = idToken.split(".")
  if (parts.length < 2) return null
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1] ?? "", "base64url").toString("utf-8"),
    ) as {
      sub?: string
      oid?: string
      preferred_username?: string
      tid?: string
      name?: string
    }
    return {
      homeAccountId: `${payload.oid ?? payload.sub ?? "unknown"}.${payload.tid ?? ""}`,
      localAccountId: payload.oid ?? payload.sub ?? "unknown",
      username: payload.preferred_username ?? "",
      tenantId: payload.tid ?? "",
      name: payload.name ?? null,
    }
  } catch {
    return null
  }
}

const postForm = (
  url: string,
  params: Record<string, string>,
): Effect.Effect<unknown, AuthenticationFailedError> =>
  pipe(
    HttpClientRequest.post(url),
    HttpClientRequest.bodyUrlParams(params),
    HttpClient.execute,
    Effect.flatMap((resp) => resp.json),
    Effect.scoped,
    Effect.mapError(
      (e) =>
        new AuthenticationFailedError({
          reason: "unknown",
          message: `Token request failed: ${String(e)}`,
          correlationId: undefined,
        }),
    ),
    Effect.provide(NodeHttpClient.layerUndici),
  )

const parseTokenJson = (
  json: unknown,
): Effect.Effect<OAuthTokenResponse, AuthenticationFailedError> => {
  if (
    typeof json !== "object" ||
    json === null ||
    !("access_token" in json) ||
    typeof (json as Record<string, unknown>)["access_token"] !== "string"
  ) {
    if (
      typeof json === "object" &&
      json !== null &&
      "error_description" in json
    ) {
      const errJson = json as OAuthErrorResponse
      return Effect.fail(
        new AuthenticationFailedError({
          reason: "invalid_grant",
          message: `Token endpoint error: ${errJson.error_description}`,
          correlationId: undefined,
        }),
      )
    }
    return Effect.fail(
      new AuthenticationFailedError({
        reason: "unknown",
        message: `Unexpected token response shape: ${JSON.stringify(json)}`,
        correlationId: undefined,
      }),
    )
  }
  return Effect.succeed(json as OAuthTokenResponse)
}

const parseDeviceCodeJson = (
  json: unknown,
): Effect.Effect<DeviceCodeResponse, AuthenticationFailedError> => {
  if (
    typeof json !== "object" ||
    json === null ||
    !("device_code" in json) ||
    typeof (json as Record<string, unknown>)["device_code"] !== "string"
  ) {
    return Effect.fail(
      new AuthenticationFailedError({
        reason: "unknown",
        message: `Unexpected device code response shape: ${JSON.stringify(json)}`,
        correlationId: undefined,
      }),
    )
  }
  return Effect.succeed(json as DeviceCodeResponse)
}

const acquireSilent = (
  stateRef: Ref.Ref<TokenCacheState>,
  config: DelegatedAuthConfig["Service"],
  tokenEndpoint: string,
) =>
  Effect.gen(function* () {
    const state = yield* Ref.get(stateRef)
    const scopesKey = makeScopesKey("any", config.scopes)

    const cachedEntry = state.tokens.get(scopesKey)
    if (
      cachedEntry &&
      !isTokenExpired(cachedEntry.expiresOn, REFRESH_BUFFER_MS)
    ) {
      const account = state.accounts.get(cachedEntry.accountId) ?? null
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
        tokenType: "Bearer" as const,
      } satisfies AccessTokenInfo
    }

    if (cachedEntry && Option.isSome(cachedEntry.refreshToken)) {
      const refreshToken = cachedEntry.refreshToken.value
      const params: Record<string, string> = {
        client_id: config.clientId,
        grant_type: "refresh_token",
        refresh_token: refreshToken,
        scope: config.scopes.join(" "),
      }
      if (config.clientSecret) {
        params["client_secret"] = config.clientSecret
      }

      const json = yield* postForm(tokenEndpoint, params)
      const raw = yield* parseTokenJson(json)
      const tokenInfo = parseTokenResponse(raw, cachedEntry.accountId)

      yield* Ref.update(stateRef, (s) => {
        const newTokens = new Map(s.tokens)
        newTokens.set(scopesKey, {
          accessToken: tokenInfo.accessToken,
          expiresOn: tokenInfo.expiresOn,
          scopes: [...tokenInfo.scopes],
          refreshToken: raw.refresh_token
            ? Option.some(raw.refresh_token)
            : Option.none(),
          accountId: cachedEntry.accountId,
        })
        return { ...s, tokens: newTokens }
      })

      return tokenInfo
    }

    return yield* Effect.fail(
      new TokenExpiredError({
        expiredAt: Date.now(),
      }),
    )
  })

const acquireByCode = (
  stateRef: Ref.Ref<TokenCacheState>,
  config: DelegatedAuthConfig["Service"],
  tokenEndpoint: string,
  authorizationCode: string,
) =>
  Effect.gen(function* () {
    const params: Record<string, string> = {
      client_id: config.clientId,
      grant_type: "authorization_code",
      code: authorizationCode,
      redirect_uri: config.redirectUri,
      scope: config.scopes.join(" "),
    }
    if (config.clientSecret) {
      params["client_secret"] = config.clientSecret
    }

    const json = yield* postForm(tokenEndpoint, params)
    const raw = yield* parseTokenJson(json)
    const account = raw.id_token ? extractAccountFromJwt(raw.id_token) : null
    const accountId = account?.homeAccountId ?? `unknown-${Date.now()}`
    const tokenInfo = parseTokenResponse(raw, accountId)
    const scopesKey = makeScopesKey(accountId, config.scopes)

    yield* Ref.update(stateRef, (s) => {
      const newTokens = new Map(s.tokens)
      const newAccounts = new Map(s.accounts)
      newTokens.set(scopesKey, {
        accessToken: tokenInfo.accessToken,
        expiresOn: tokenInfo.expiresOn,
        scopes: [...tokenInfo.scopes],
        refreshToken: raw.refresh_token
          ? Option.some(raw.refresh_token)
          : Option.none(),
        accountId,
      })
      if (account) {
        newAccounts.set(accountId, account)
      }
      return { tokens: newTokens, accounts: newAccounts }
    })

    if (config.cachePlugin) {
      const ctx = makeTokenCacheContext(stateRef)
      yield* config.cachePlugin.afterCacheAccess(ctx)
    }

    return tokenInfo
  })

type PollError =
  | { readonly _tag: "pending" }
  | { readonly _tag: "fatal"; readonly error: AuthenticationFailedError }

const pollDeviceCodeToken = (
  tokenEndpoint: string,
  clientId: string,
  deviceCode: string,
  pollInterval: Duration.Duration,
): Effect.Effect<OAuthTokenResponse, AuthenticationFailedError> =>
  Effect.gen(function* () {
    const params: Record<string, string> = {
      client_id: clientId,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
      device_code: deviceCode,
    }

    const json = yield* postForm(tokenEndpoint, params).pipe(
      Effect.mapError(
        (e): PollError => ({
          _tag: "fatal",
          error: e,
        }),
      ),
    )

    const shaped = json as Record<string, unknown>
    if (
      "error" in shaped &&
      shaped["error"] === "authorization_pending"
    ) {
      return yield* Effect.fail<PollError>({ _tag: "pending" })
    }

    if ("error" in shaped) {
      const errJson = json as OAuthErrorResponse
      return yield* Effect.fail<PollError>({
        _tag: "fatal",
        error: new AuthenticationFailedError({
          reason: "unknown",
          message: `Device code poll failed: ${errJson.error_description}`,
          correlationId: undefined,
        }),
      })
    }

    const raw = yield* parseTokenJson(json).pipe(
      Effect.mapError(
        (e): PollError => ({ _tag: "fatal", error: e }),
      ),
    )
    return raw
  }).pipe(
    Effect.catch((e: PollError) => {
      if (e._tag === "pending") {
        return pipe(
          Effect.sleep(pollInterval),
          Effect.flatMap(() =>
            pollDeviceCodeToken(
              tokenEndpoint,
              clientId,
              deviceCode,
              pollInterval,
            ),
          ),
        )
      }
      return Effect.fail(e.error)
    }),
  )

const acquireByDeviceCode = (
  stateRef: Ref.Ref<TokenCacheState>,
  config: DelegatedAuthConfig["Service"],
  tokenEndpoint: string,
) =>
  Effect.gen(function* () {
    const deviceCodeEndpoint = tokenEndpoint.replace("/token", "/devicecode")

    const deviceCodeParams: Record<string, string> = {
      client_id: config.clientId,
      scope: config.scopes.join(" "),
    }

    const deviceCodeJson = yield* postForm(deviceCodeEndpoint, deviceCodeParams)
    const deviceCodeRaw = yield* parseDeviceCodeJson(deviceCodeJson)

    const pollInterval = Duration.millis(deviceCodeRaw.interval * 1000)
    const raw = yield* pollDeviceCodeToken(
      tokenEndpoint,
      config.clientId,
      deviceCodeRaw.device_code,
      pollInterval,
    )

    const account = raw.id_token ? extractAccountFromJwt(raw.id_token) : null
    const accountId = account?.homeAccountId ?? `unknown-${Date.now()}`
    const tokenInfo = parseTokenResponse(raw, accountId)
    const scopesKey = makeScopesKey(accountId, config.scopes)

    yield* Ref.update(stateRef, (s) => {
      const newTokens = new Map(s.tokens)
      const newAccounts = new Map(s.accounts)
      newTokens.set(scopesKey, {
        accessToken: tokenInfo.accessToken,
        expiresOn: tokenInfo.expiresOn,
        scopes: [...tokenInfo.scopes],
        refreshToken: raw.refresh_token
          ? Option.some(raw.refresh_token)
          : Option.none(),
        accountId,
      })
      if (account) {
        newAccounts.set(accountId, account)
      }
      return { tokens: newTokens, accounts: newAccounts }
    })

    return { tokenInfo, deviceCodeMessage: deviceCodeRaw.message }
  })

const proactiveRefreshFiber = (
  stateRef: Ref.Ref<TokenCacheState>,
  config: DelegatedAuthConfig["Service"],
  tokenEndpoint: string,
) =>
  pipe(
    Effect.gen(function* () {
      const state = yield* Ref.get(stateRef)
      const now = Date.now()

      for (const [key, entry] of state.tokens) {
        const msUntilExpiry = entry.expiresOn.getTime() - now
        if (msUntilExpiry > 0 && msUntilExpiry <= REFRESH_BUFFER_MS) {
          if (Option.isSome(entry.refreshToken)) {
            const params: Record<string, string> = {
              client_id: config.clientId,
              grant_type: "refresh_token",
              refresh_token: entry.refreshToken.value,
              scope: config.scopes.join(" "),
            }
            if (config.clientSecret) {
              params["client_secret"] = config.clientSecret
            }

            const refreshed = yield* postForm(tokenEndpoint, params).pipe(
              Effect.flatMap(parseTokenJson),
              Effect.orElseSucceed(() => null),
            )

            if (refreshed) {
              yield* Ref.update(stateRef, (s) => {
                const newTokens = new Map(s.tokens)
                newTokens.set(key, {
                  accessToken: refreshed.access_token,
                  expiresOn: new Date(
                    Date.now() + refreshed.expires_in * 1000,
                  ),
                  scopes: refreshed.scope.split(" "),
                  refreshToken: refreshed.refresh_token
                    ? Option.some(refreshed.refresh_token)
                    : entry.refreshToken,
                  accountId: entry.accountId,
                })
                return { ...s, tokens: newTokens }
              })

              if (config.cachePlugin) {
                const ctx = makeTokenCacheContext(stateRef)
                yield* config.cachePlugin.afterCacheAccess(ctx)
              }
            }
          }
        }
      }
    }),
    Effect.repeat(Schedule.spaced(Duration.minutes(1))),
    Effect.ignore,
  )

const makeService = (
  config: DelegatedAuthConfig["Service"],
  stateRef: Ref.Ref<TokenCacheState>,
): MsGraphAuthInterface => {
  const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`

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
        const newAccounts = new Map(s.accounts)
        newAccounts.delete(accountId)
        const newTokens = new Map(
          [...s.tokens.entries()].filter(([, v]) => v.accountId !== accountId),
        )
        return { tokens: newTokens, accounts: newAccounts }
      }),
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const DelegatedAuthLive = <_P extends string = string>() => Layer.effect(
  DelegatedAuth,
  Effect.gen(function* () {
    const config = yield* DelegatedAuthConfig
    const stateRef = yield* Ref.make<TokenCacheState>(emptyTokenCacheState)

    if (config.cachePlugin) {
      const ctx = makeTokenCacheContext(stateRef)
      yield* config.cachePlugin.beforeCacheAccess(ctx)
    }

    const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`
    const refreshFiber = yield* Effect.forkScoped(
      proactiveRefreshFiber(stateRef, config, tokenEndpoint),
    )

    yield* Effect.addFinalizer(() => Fiber.interrupt(refreshFiber))

    return DelegatedAuth.of(makeService(config, stateRef))
  }),
)
