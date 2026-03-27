import { HttpClient, HttpClientRequest } from "effect/unstable/http"
import { NodeHttpClient } from "@effect/platform-node"
import { Effect, Layer, Option, Ref, pipe } from "effect"
import { AuthenticationFailedError } from "../Errors/errors"
import type { AccessTokenInfo, MsGraphAuthInterface } from "./MsGraphAuth"
import { ManagedIdentityAuth } from "./MsGraphAuth"
import { ManagedIdentityAuthConfig } from "./MsGraphAuthConfig"
import { REFRESH_BUFFER_MS, isTokenExpired } from "./TokenCache"

const IMDS_ENDPOINT =
  "http://169.254.169.254/metadata/identity/oauth2/token"
const IMDS_API_VERSION = "2018-02-01"

interface ImdsTokenResponse {
  readonly access_token: string
  readonly expires_on: string
  readonly resource: string
  readonly token_type: string
  readonly client_id?: string
}

interface ImdsErrorResponse {
  readonly error: string
  readonly error_description: string
}

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

const parseImdsJson = (
  json: unknown,
): Effect.Effect<ImdsTokenResponse, AuthenticationFailedError> => {
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
      const errJson = json as ImdsErrorResponse
      return Effect.fail(
        new AuthenticationFailedError({
          reason: "unknown",
          message: `IMDS token acquisition failed: ${errJson.error_description}`,
          correlationId: undefined,
        }),
      )
    }
    return Effect.fail(
      new AuthenticationFailedError({
        reason: "unknown",
        message: `Unexpected IMDS response shape: ${JSON.stringify(json)}`,
        correlationId: undefined,
      }),
    )
  }
  return Effect.succeed(json as ImdsTokenResponse)
}

const acquireFromImds = (
  scopes: ReadonlyArray<string>,
  clientId?: string,
): Effect.Effect<ImdsTokenResponse, AuthenticationFailedError> =>
  Effect.gen(function* () {
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

    const json = yield* pipe(
      HttpClientRequest.get(imdsUrl),
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
  })

const parseImdsExpiresOn = (expiresOn: string): Date => {
  const asUnixSeconds = Number(expiresOn)
  if (!Number.isNaN(asUnixSeconds)) {
    return new Date(asUnixSeconds * 1000)
  }
  return new Date(expiresOn)
}

const makeService = (
  config: {
    readonly scopes: ReadonlyArray<string>
    readonly clientId?: string
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
  })

  return {
    grantedScopes: config.scopes,
    acquireToken,
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
