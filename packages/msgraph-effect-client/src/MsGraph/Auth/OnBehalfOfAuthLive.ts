import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import { Effect, Layer, Option, Ref, Result, Schema } from "effect"
import { AuthenticationFailedError } from "../Errors/errors"
import type { AccessTokenInfo, AccountInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { OnBehalfOfAuth } from "./MsGraphAuth"
import { OnBehalfOfAuthConfig } from "./MsGraphAuthConfig"
import { REFRESH_BUFFER_MS, isTokenExpired } from "./TokenCache"

const OAuthTokenResponseSchema = Schema.Struct({
  access_token: Schema.String,
  token_type: Schema.String,
  expires_in: Schema.Number,
  scope: Schema.String,
  refresh_token: Schema.optionalKey(Schema.String),
  id_token: Schema.optionalKey(Schema.String),
})

const OAuthErrorResponseSchema = Schema.Struct({
  error: Schema.String,
  error_description: Schema.optionalKey(Schema.String),
})

type OAuthTokenResponse = typeof OAuthTokenResponseSchema.Type

const parseTokenJson = Effect.fn("OnBehalfOfAuth.parseTokenJson")(
  function*(json: unknown): Effect.fn.Return<OAuthTokenResponse, AuthenticationFailedError> {
    const errorCheck = Schema.decodeUnknownResult(OAuthErrorResponseSchema)(json)
    const errorDescription = Result.match(errorCheck, {
      onSuccess: (r) => r.error_description,
      onFailure: () => undefined,
    })
    if (errorDescription) {
      return yield* Effect.fail(
        new AuthenticationFailedError({
          reason: "invalid_grant",
          message: `OBO token exchange failed: ${errorDescription}`,
          correlationId: undefined,
        }),
      )
    }

    return yield* Schema.decodeUnknownEffect(OAuthTokenResponseSchema)(json).pipe(
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: "unknown",
            message: `Unexpected OBO response shape: ${e.message}`,
            correlationId: undefined,
          }),
      ),
    )
  },
)

const extractAccountFromJwt = (accessToken: string): AccountInfo | null => {
  const parts = accessToken.split(".")
  if (parts.length < 2) return null
  try {
    const payload = JSON.parse(
      Buffer.from(parts[1] ?? "", "base64url").toString("utf-8"),
    ) as {
      sub?: string
      oid?: string
      preferred_username?: string
      upn?: string
      tid?: string
      name?: string
    }
    const localAccountId = payload.oid ?? payload.sub ?? "unknown"
    const tenantId = payload.tid ?? ""
    return {
      homeAccountId: `${localAccountId}.${tenantId}`,
      localAccountId,
      username: payload.preferred_username ?? payload.upn ?? "",
      tenantId,
      name: payload.name ?? null,
    }
  } catch {
    return null
  }
}

const exchangeOboToken = Effect.fn("OnBehalfOfAuth.exchangeOboToken")(
  function*(
    userAssertion: string,
    clientId: string,
    clientSecret: string,
    scopes: ReadonlyArray<string>,
    tokenEndpoint: string,
  ): Effect.fn.Return<OAuthTokenResponse, AuthenticationFailedError> {
    const json = yield* HttpClientRequest.post(tokenEndpoint).pipe(
      HttpClientRequest.bodyUrlParams({
        client_id: clientId,
        client_secret: clientSecret,
        grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
        assertion: userAssertion,
        requested_token_use: "on_behalf_of",
        scope: scopes.join(" "),
      }),
      HttpClient.execute,
      Effect.flatMap((resp) => resp.json),
      Effect.scoped,
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: "unknown",
            message: `OBO request failed: ${String(e)}`,
            correlationId: undefined,
          }),
      ),
      Effect.provide(NodeHttpClient.layerUndici),
    )

    return yield* parseTokenJson(json)
  },
)

const acquireOboToken = Effect.fn("OnBehalfOfAuth.acquireOboToken")(
  function*(
    config: {
      readonly clientId: string
      readonly clientSecret: string
      readonly scopes: ReadonlyArray<string>
      readonly tokenEndpoint: string
      readonly userAssertionProvider: Effect.Effect<string, AuthenticationFailedError>
    },
    cachedRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
  ): Effect.fn.Return<AccessTokenInfo, AuthenticationFailedError> {
    const cached = yield* Ref.get(cachedRef).pipe(
      Effect.map(Option.filter((token) => !isTokenExpired(token.expiresOn, REFRESH_BUFFER_MS))),
    )

    return yield* Option.match(cached, {
      onSome: (token) => Effect.succeed(token),
      onNone: () =>
        Effect.gen(function* () {
          const userAssertion = yield* config.userAssertionProvider

          const raw = yield* exchangeOboToken(
            userAssertion,
            config.clientId,
            config.clientSecret,
            config.scopes,
            config.tokenEndpoint,
          )

          const expiresOn = new Date(Date.now() + raw.expires_in * 1000)
          const account = extractAccountFromJwt(raw.access_token)
          const tokenInfo: AccessTokenInfo = {
            accessToken: raw.access_token,
            expiresOn,
            scopes: raw.scope.split(" "),
            account,
            tokenType: "Bearer",
          }

          yield* Ref.set(cachedRef, Option.some(tokenInfo))

          return tokenInfo
        }),
    })
  },
)

const getCachedAccounts = Effect.fn("OnBehalfOfAuth.getCachedAccounts")(
  function*(
    cachedRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
  ): Effect.fn.Return<ReadonlyArray<AccountInfo>, never> {
    const cached = yield* Ref.get(cachedRef)
    return Option.match(cached, {
      onNone: () => [] as ReadonlyArray<AccountInfo>,
      onSome: (token) =>
        token.account !== null ? [token.account] : ([] as ReadonlyArray<AccountInfo>),
    })
  },
)

const makeService = (
  config: {
    readonly clientId: string
    readonly clientSecret: string
    readonly scopes: ReadonlyArray<string>
    readonly tokenEndpoint: string
    readonly userAssertionProvider: Effect.Effect<
      string,
      AuthenticationFailedError
    >
  },
  cachedRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
): MsGraphAuthInterface => {
  return {
    grantedScopes: config.scopes,
    acquireToken: acquireOboToken(config, cachedRef),
    getCachedAccounts: getCachedAccounts(cachedRef),
    removeCachedAccount: (_accountId: string) =>
      Ref.set(cachedRef, Option.none()),
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const OnBehalfOfAuthLive = <_P extends string = string>() => Layer.effect(
  OnBehalfOfAuth,
  Effect.gen(function* () {
    const config = yield* OnBehalfOfAuthConfig
    const cachedRef = yield* Ref.make<Option.Option<AccessTokenInfo>>(
      Option.none(),
    )
    const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`

    return OnBehalfOfAuth.of(makeService(
      {
        clientId: config.clientId,
        clientSecret: config.clientSecret,
        scopes: config.scopes,
        tokenEndpoint,
        userAssertionProvider: config.userAssertionProvider,
      },
      cachedRef,
    ))
  }),
)
