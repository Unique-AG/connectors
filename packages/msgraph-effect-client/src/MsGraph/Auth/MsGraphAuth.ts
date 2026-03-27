import { Effect, ServiceMap } from "effect"
import type { AuthenticationFailedError, TokenExpiredError } from "../Errors/errors"

export type AuthFlow = "Delegated" | "Application" | "OnBehalfOf" | "ManagedIdentity"

export interface AccessTokenInfo {
  readonly accessToken: string
  readonly expiresOn: Date
  readonly scopes: ReadonlyArray<string>
  readonly account: AccountInfo | null
  readonly tokenType: "Bearer"
}

export interface AccountInfo {
  readonly homeAccountId: string
  readonly localAccountId: string
  readonly username: string
  readonly tenantId: string
  readonly name: string | null
}

export interface MsGraphAuthInterface {
  readonly acquireToken: Effect.Effect<
    AccessTokenInfo,
    TokenExpiredError | AuthenticationFailedError
  >

  readonly getCachedAccounts: Effect.Effect<ReadonlyArray<AccountInfo>, never>

  readonly removeCachedAccount: (
    accountId: string,
  ) => Effect.Effect<void, never>

  readonly grantedScopes: ReadonlyArray<string>
}

export class DelegatedAuth extends ServiceMap.Service<DelegatedAuth, MsGraphAuthInterface>()(
  "MsGraph/Auth/Delegated",
) {}

export class ApplicationAuth extends ServiceMap.Service<ApplicationAuth, MsGraphAuthInterface>()(
  "MsGraph/Auth/Application",
) {}

export class OnBehalfOfAuth extends ServiceMap.Service<OnBehalfOfAuth, MsGraphAuthInterface>()(
  "MsGraph/Auth/OnBehalfOf",
) {}

export class ManagedIdentityAuth extends ServiceMap.Service<ManagedIdentityAuth, MsGraphAuthInterface>()(
  "MsGraph/Auth/ManagedIdentity",
) {}
