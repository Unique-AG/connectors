import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import { Effect, Layer, Option, Ref, pipe } from "effect"
import { AuthenticationFailedError } from "../Errors/errors"
import type { AccessTokenInfo, AccountInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { OnBehalfOfAuth } from "./MsGraphAuth"
import { OnBehalfOfAuthConfig } from "./MsGraphAuthConfig"
import { REFRESH_BUFFER_MS, isTokenExpired } from "./TokenCache"

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
          message: `OBO token exchange failed: ${errJson.error_description}`,
          correlationId: undefined,
        }),
      )
    }
    return Effect.fail(
      new AuthenticationFailedError({
        reason: "unknown",
        message: `Unexpected OBO response shape: ${JSON.stringify(json)}`,
        correlationId: undefined,
      }),
    )
  }
  return Effect.succeed(json as OAuthTokenResponse)
}

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

const exchangeOboToken = (
  userAssertion: string,
  clientId: string,
  clientSecret: string,
  scopes: ReadonlyArray<string>,
  tokenEndpoint: string,
): Effect.Effect<OAuthTokenResponse, AuthenticationFailedError> =>
  pipe(
    HttpClientRequest.post(tokenEndpoint),
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
    Effect.flatMap(parseTokenJson),
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
  const acquireToken: Effect.Effect<
    AccessTokenInfo,
    AuthenticationFailedError
  > = Effect.gen(function* () {
    const cached = yield* Ref.get(cachedRef)

    if (Option.isSome(cached)) {
      const token = cached.value
      if (!isTokenExpired(token.expiresOn, REFRESH_BUFFER_MS)) {
        return token
      }
    }

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
  })

  return {
    grantedScopes: config.scopes,
    acquireToken,
    getCachedAccounts: Effect.gen(function* () {
      const cached = yield* Ref.get(cachedRef)
      if (Option.isSome(cached) && cached.value.account !== null) {
        return [cached.value.account]
      }
      return []
    }),
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
