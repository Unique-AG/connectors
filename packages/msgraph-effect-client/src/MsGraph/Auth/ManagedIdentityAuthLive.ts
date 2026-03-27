import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import { Effect, Layer, Option, Ref, Result, Schema } from "effect"
import { AuthenticationFailedError } from "../Errors/errors"
import type { AccessTokenInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { ManagedIdentityAuth } from "./MsGraphAuth"
import { ManagedIdentityAuthConfig } from "./MsGraphAuthConfig"
import { REFRESH_BUFFER_MS, isTokenExpired } from "./TokenCache"

const IMDS_ENDPOINT =
  "http://169.254.169.254/metadata/identity/oauth2/token"
const IMDS_API_VERSION = "2018-02-01"

const ImdsTokenResponseSchema = Schema.Struct({
  access_token: Schema.String,
  expires_on: Schema.String,
  resource: Schema.String,
  token_type: Schema.String,
  client_id: Schema.optionalKey(Schema.String),
})

const ImdsErrorResponseSchema = Schema.Struct({
  error: Schema.String,
  error_description: Schema.optionalKey(Schema.String),
})

type ImdsTokenResponse = typeof ImdsTokenResponseSchema.Type

const extractResourceFromScope = (scope: string): string => {
  if (scope.endsWith("/.default")) {
    return scope.slice(0, -"/.default".length)
  }
  try {
    const url = new URL(scope)
    return `${url.protocol}//${url.host}`
  } catch {
    return scope
  }
}

const parseImdsJson = Effect.fn("ManagedIdentityAuth.parseImdsJson")(
  function*(json: unknown): Effect.fn.Return<ImdsTokenResponse, AuthenticationFailedError> {
    const errorCheck = Schema.decodeUnknownResult(ImdsErrorResponseSchema)(json)
    const errorDescription = Result.match(errorCheck, {
      onSuccess: (r) => r.error_description,
      onFailure: () => undefined,
    })
    if (errorDescription) {
      return yield* Effect.fail(
        new AuthenticationFailedError({
          reason: "unknown",
          message: `IMDS token acquisition failed: ${errorDescription}`,
          correlationId: undefined,
        }),
      )
    }

    return yield* Schema.decodeUnknownEffect(ImdsTokenResponseSchema)(json).pipe(
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: "unknown",
            message: `Unexpected IMDS response shape: ${e.message}`,
            correlationId: undefined,
          }),
      ),
    )
  },
)

const acquireFromImds = Effect.fn("ManagedIdentityAuth.acquireFromImds")(
  function*(
    scopes: ReadonlyArray<string>,
    clientId?: string,
  ): Effect.fn.Return<ImdsTokenResponse, AuthenticationFailedError> {
    const primaryScope = scopes[0]
    if (!primaryScope) {
      return yield* Effect.fail(
        new AuthenticationFailedError({
          reason: "invalid_client",
          message:
            "At least one scope must be provided for managed identity token acquisition",
          correlationId: undefined,
        }),
      )
    }

    const resource = extractResourceFromScope(primaryScope)

    const urlParams: Record<string, string> = {
      "api-version": IMDS_API_VERSION,
      resource,
    }

    if (clientId) {
      urlParams["client_id"] = clientId
    }

    const queryString = Object.entries(urlParams)
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
      .join("&")

    const imdsUrl = `${IMDS_ENDPOINT}?${queryString}`

    const json = yield* HttpClientRequest.get(imdsUrl).pipe(
      HttpClientRequest.setHeader("Metadata", "true"),
      HttpClient.execute,
      Effect.flatMap((resp) => resp.json),
      Effect.scoped,
      Effect.mapError(
        (e) =>
          new AuthenticationFailedError({
            reason: "unknown",
            message: `IMDS request failed: ${String(e)}`,
            correlationId: undefined,
          }),
      ),
      Effect.provide(NodeHttpClient.layerUndici),
    )

    return yield* parseImdsJson(json)
  },
)

const parseImdsExpiresOn = (expiresOn: string): Date => {
  const asUnixSeconds = Number(expiresOn)
  if (!Number.isNaN(asUnixSeconds)) {
    return new Date(asUnixSeconds * 1000)
  }
  return new Date(expiresOn)
}

const acquireManagedIdentityToken = Effect.fn("ManagedIdentityAuth.acquireManagedIdentityToken")(
  function*(
    config: { readonly scopes: ReadonlyArray<string>; readonly clientId?: string },
    cachedRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
  ): Effect.fn.Return<AccessTokenInfo, AuthenticationFailedError> {
    const cached = yield* Ref.get(cachedRef).pipe(
      Effect.map(Option.filter((token) => !isTokenExpired(token.expiresOn, REFRESH_BUFFER_MS))),
    )

    return yield* Option.match(cached, {
      onSome: (token) => Effect.succeed(token),
      onNone: () =>
        Effect.gen(function* () {
          const raw = yield* acquireFromImds(config.scopes, config.clientId)

          const expiresOn = parseImdsExpiresOn(raw.expires_on)
          const tokenInfo: AccessTokenInfo = {
            accessToken: raw.access_token,
            expiresOn,
            scopes: [...config.scopes],
            account: null,
            tokenType: "Bearer",
          }

          yield* Ref.set(cachedRef, Option.some(tokenInfo))

          return tokenInfo
        }),
    })
  },
)

const makeService = (
  config: {
    readonly scopes: ReadonlyArray<string>
    readonly clientId?: string
  },
  cachedRef: Ref.Ref<Option.Option<AccessTokenInfo>>,
): MsGraphAuthInterface => {
  return {
    grantedScopes: config.scopes,
    acquireToken: acquireManagedIdentityToken(config, cachedRef),
    getCachedAccounts: Effect.succeed([]),
    removeCachedAccount: (_accountId: string) =>
      Ref.set(cachedRef, Option.none()),
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export const ManagedIdentityAuthLive = <_P extends string = string>() => Layer.effect(
  ManagedIdentityAuth,
  Effect.gen(function* () {
    const config = yield* ManagedIdentityAuthConfig
    const cachedRef = yield* Ref.make<Option.Option<AccessTokenInfo>>(
      Option.none(),
    )

    return ManagedIdentityAuth.of(makeService(
      { scopes: config.scopes, clientId: config.clientId },
      cachedRef,
    ))
  }),
)
