import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import { Effect, Layer, Option, Ref, pipe } from "effect"
import { createSign } from "node:crypto"
import { AuthenticationFailedError } from "../Errors/errors"
import type { AccessTokenInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { ApplicationAuth } from "./MsGraphAuth"
import { ApplicationAuthConfig } from "./MsGraphAuthConfig"
import {
  REFRESH_BUFFER_MS,
  emptyTokenCacheState,
  isTokenExpired,
  makeTokenCacheContext,
  type TokenCacheState,
} from "./TokenCache"

interface OAuthTokenResponse {
  readonly access_token: string
  readonly token_type: string
  readonly expires_in: number
  readonly scope: string
}

interface OAuthErrorResponse {
  readonly error: string
  readonly error_description: string
}

const base64UrlEncode = (input: string | Buffer): string => {
  const buf = typeof input === "string" ? Buffer.from(input) : input
  return buf.toString("base64url")
}

const makeClientAssertion = (
  clientId: string,
  tokenEndpoint: string,
  thumbprint: string,
  privateKey: string,
  x5c?: string,
): string => {
  const now = Math.floor(Date.now() / 1000)
  const header = x5c
    ? { alg: "RS256", typ: "JWT", x5c: [x5c] }
    : {
        alg: "RS256",
        typ: "JWT",
        x5t: Buffer.from(thumbprint, "hex").toString("base64url"),
      }

  const payload = {
    aud: tokenEndpoint,
    iss: clientId,
    sub: clientId,
    jti: base64UrlEncode(Buffer.from(Math.random().toString())),
    nbf: now,
    exp: now + 600,
  }

  const headerEncoded = base64UrlEncode(JSON.stringify(header))
  const payloadEncoded = base64UrlEncode(JSON.stringify(payload))
  const signingInput = `${headerEncoded}.${payloadEncoded}`

  const signer = createSign("RSA-SHA256")
  signer.update(signingInput)
  const signature = signer.sign(privateKey, "base64url")

  return `${signingInput}.${signature}`
}

const buildTokenParams = (
  config: ApplicationAuthConfig["Service"],
  tokenEndpoint: string,
): Effect.Effect<Record<string, string>, AuthenticationFailedError> => {
  const base: Record<string, string> = {
    client_id: config.clientId,
    grant_type: "client_credentials",
    scope: config.scopes.join(" "),
  }

  if (config.clientSecret) {
    return Effect.succeed({ ...base, client_secret: config.clientSecret })
  }

  if (config.clientCertificate) {
    const { thumbprint, privateKey, x5c } = config.clientCertificate
    return Effect.try({
      try: () => ({
        ...base,
        client_assertion_type:
          "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
        client_assertion: makeClientAssertion(
          config.clientId,
          tokenEndpoint,
          thumbprint,
          privateKey,
          x5c,
        ),
      }),
      catch: (e) =>
        new AuthenticationFailedError({
          reason: "unknown",
          message: `Failed to build client assertion: ${String(e)}`,
          correlationId: undefined,
        }),
    })
  }

  return Effect.fail(
    new AuthenticationFailedError({
      reason: "invalid_client",
      message:
        "ApplicationAuthConfig requires either clientSecret or clientCertificate",
      correlationId: undefined,
    }),
  )
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

const acquireClientCredentials = (
  config: ApplicationAuthConfig["Service"],
  tokenEndpoint: string,
): Effect.Effect<OAuthTokenResponse, AuthenticationFailedError> =>
  Effect.gen(function* () {
    const params = yield* buildTokenParams(config, tokenEndpoint)

    const json = yield* pipe(
      HttpClientRequest.post(tokenEndpoint),
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

    return yield* parseTokenJson(json)
  })

const makeService = (
  config: ApplicationAuthConfig["Service"],
  cachedTokenRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
  cacheStateRef: Ref.Ref<TokenCacheState>,
): MsGraphAuthInterface => {
  const tokenEndpoint = `${config.authority}/oauth2/v2.0/token`

  const acquireToken: Effect.Effect<
    AccessTokenInfo,
    AuthenticationFailedError
  > = Effect.gen(function* () {
    const cached = yield* Ref.get(cachedTokenRef)

    if (Option.isSome(cached)) {
      const token = cached.value
      if (!isTokenExpired(token.expiresOn, REFRESH_BUFFER_MS)) {
        return token
      }
    }

    const raw = yield* acquireClientCredentials(config, tokenEndpoint)
    const expiresOn = new Date(Date.now() + raw.expires_in * 1000)
    const tokenInfo: AccessTokenInfo = {
      accessToken: raw.access_token,
      expiresOn,
      scopes: raw.scope.split(" "),
      account: null,
      tokenType: "Bearer",
    }

    yield* Ref.set(cachedTokenRef, Option.some(tokenInfo))

    if (config.cachePlugin) {
      const ctx = makeTokenCacheContext(cacheStateRef)
      yield* config.cachePlugin.afterCacheAccess(ctx)
    }

    return tokenInfo
  })

  return {
    grantedScopes: config.scopes,
    acquireToken,
    getCachedAccounts: Effect.succeed([]),
    removeCachedAccount: (_accountId: string) =>
      Ref.set(cachedTokenRef, Option.none()),
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ApplicationAuthLive = <_P extends string = string>() => Layer.effect(
  ApplicationAuth,
  Effect.gen(function* () {
    const config = yield* ApplicationAuthConfig
    const cachedTokenRef = yield* Ref.make<Option.Option<AccessTokenInfo>>(
      Option.none(),
    )
    const cacheStateRef = yield* Ref.make<TokenCacheState>(
      emptyTokenCacheState,
    )

    if (config.cachePlugin) {
      const ctx = makeTokenCacheContext(cacheStateRef)
      yield* config.cachePlugin.beforeCacheAccess(ctx)
    }

    return ApplicationAuth.of(makeService(config, cachedTokenRef, cacheStateRef))
  }),
)
