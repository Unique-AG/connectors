import { Context, Effect } from "effect"
import type { TokenCachePlugin } from "./TokenCache"
import type { AuthenticationFailedError } from "../Errors/errors"

export interface DelegatedAuthConfig {
  readonly clientId: string
  readonly authority: string
  readonly clientSecret?: string
  readonly redirectUri: string
  readonly scopes: ReadonlyArray<string>
  readonly cachePlugin?: TokenCachePlugin
}

export interface ApplicationAuthConfig {
  readonly clientId: string
  readonly authority: string
  readonly clientSecret?: string
  readonly clientCertificate?: {
    readonly thumbprint: string
    readonly privateKey: string
    readonly x5c?: string
  }
  readonly scopes: ReadonlyArray<string>
  readonly cachePlugin?: TokenCachePlugin
}

export interface OnBehalfOfAuthConfig {
  readonly clientId: string
  readonly authority: string
  readonly clientSecret: string
  readonly scopes: ReadonlyArray<string>
  readonly userAssertionProvider: Effect.Effect<
    string,
    AuthenticationFailedError
  >
}

export interface ManagedIdentityAuthConfig {
  readonly clientId?: string
  readonly scopes: ReadonlyArray<string>
}

export const DelegatedAuthConfig =
  Context.GenericTag<DelegatedAuthConfig>("MsGraph/DelegatedAuthConfig")

export const ApplicationAuthConfig =
  Context.GenericTag<ApplicationAuthConfig>("MsGraph/ApplicationAuthConfig")

export const OnBehalfOfAuthConfig =
  Context.GenericTag<OnBehalfOfAuthConfig>("MsGraph/OnBehalfOfAuthConfig")

export const ManagedIdentityAuthConfig =
  Context.GenericTag<ManagedIdentityAuthConfig>(
    "MsGraph/ManagedIdentityAuthConfig",
  )
