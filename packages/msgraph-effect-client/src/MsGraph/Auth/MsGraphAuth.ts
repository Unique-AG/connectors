import { Context, Effect } from "effect"
import type { AuthenticationFailedError, TokenExpiredError } from "../Errors/errors"

export type AuthFlow = "Delegated" | "Application"

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

export interface MsGraphAuth<F extends AuthFlow, P extends string> {
  readonly _flow: F
  readonly _permissions: P

  readonly acquireToken: Effect.Effect<
    AccessTokenInfo,
    TokenExpiredError | AuthenticationFailedError
  >

  readonly getCachedAccounts: Effect.Effect<ReadonlyArray<AccountInfo>, never>

  readonly removeCachedAccount: (
    accountId: string,
  ) => Effect.Effect<void, never>

  readonly grantedScopes: ReadonlyArray<P>
}

export const MsGraphAuthTag = <F extends AuthFlow, P extends string>(
  flow: F,
) => Context.GenericTag<MsGraphAuth<F, P>>(`MsGraph/Auth/${flow}`)

export const DelegatedAuth = <P extends string>() =>
  MsGraphAuthTag<"Delegated", P>("Delegated")

export const ApplicationAuth = <P extends string>() =>
  MsGraphAuthTag<"Application", P>("Application")
