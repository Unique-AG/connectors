import { Effect, ServiceMap } from "effect"
import type { TokenCachePlugin } from "./TokenCache"
import type { AuthenticationFailedError } from "../Errors/errors"

export interface DelegatedAuthConfigShape {
  readonly clientId: string
  readonly authority: string
  readonly clientSecret?: string
  readonly redirectUri: string
  readonly scopes: ReadonlyArray<string>
  readonly cachePlugin?: TokenCachePlugin
}

export interface ApplicationAuthConfigShape {
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

export interface OnBehalfOfAuthConfigShape {
  readonly clientId: string
  readonly authority: string
  readonly clientSecret: string
  readonly scopes: ReadonlyArray<string>
  readonly userAssertionProvider: Effect.Effect<
    string,
    AuthenticationFailedError
  >
}

export interface ManagedIdentityAuthConfigShape {
  readonly clientId?: string
  readonly scopes: ReadonlyArray<string>
}

export class DelegatedAuthConfig extends ServiceMap.Service<DelegatedAuthConfig, DelegatedAuthConfigShape>()(
  "MsGraph/Auth/DelegatedAuthConfig",
) {}

export class ApplicationAuthConfig extends ServiceMap.Service<ApplicationAuthConfig, ApplicationAuthConfigShape>()(
  "MsGraph/Auth/ApplicationAuthConfig",
) {}

export class OnBehalfOfAuthConfig extends ServiceMap.Service<OnBehalfOfAuthConfig, OnBehalfOfAuthConfigShape>()(
  "MsGraph/Auth/OnBehalfOfAuthConfig",
) {}

export class ManagedIdentityAuthConfig extends ServiceMap.Service<ManagedIdentityAuthConfig, ManagedIdentityAuthConfigShape>()(
  "MsGraph/Auth/ManagedIdentityAuthConfig",
) {}
