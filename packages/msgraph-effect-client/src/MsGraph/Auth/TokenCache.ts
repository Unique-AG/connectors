import { Effect, Option, Ref, ServiceMap } from "effect"

export interface TokenCachePlugin {
  readonly beforeCacheAccess: (
    cache: TokenCacheContext,
  ) => Effect.Effect<void, never>
  readonly afterCacheAccess: (
    cache: TokenCacheContext,
  ) => Effect.Effect<void, never>
}

export interface TokenCacheContext {
  readonly cacheHasChanged: boolean
  readonly serialize: () => string
  readonly deserialize: (data: string) => void
}

export interface CachedTokenEntry {
  readonly accessToken: string
  readonly expiresOn: Date
  readonly scopes: ReadonlyArray<string>
  readonly refreshToken: Option.Option<string>
  readonly accountId: string
}

export interface TokenCacheState {
  readonly tokens: ReadonlyMap<string, CachedTokenEntry>
  readonly accounts: ReadonlyMap<string, AccountCacheEntry>
}

export interface AccountCacheEntry {
  readonly homeAccountId: string
  readonly localAccountId: string
  readonly username: string
  readonly tenantId: string
  readonly name: string | null
}

export const emptyTokenCacheState: TokenCacheState = {
  tokens: new Map(),
  accounts: new Map(),
}

export class TokenCacheStateRef extends ServiceMap.Service<TokenCacheStateRef, Ref.Ref<TokenCacheState>>()(
  "MsGraph/Auth/TokenCacheStateRef",
) {}

export const makeScopesKey = (
  accountId: string,
  scopes: ReadonlyArray<string>,
): string => `${accountId}:${[...scopes].sort().join(" ")}`

export const isTokenExpired = (expiresOn: Date, bufferMs = 0): boolean =>
  expiresOn.getTime() - Date.now() <= bufferMs

export const REFRESH_BUFFER_MS = 5 * 60 * 1000

export const makeTokenCacheContext = (
  stateRef: Ref.Ref<TokenCacheState>,
): TokenCacheContext => {
  let hasChanged = false

  return {
    get cacheHasChanged() {
      return hasChanged
    },
    serialize: () => {
      let state: TokenCacheState = {
        tokens: new Map(),
        accounts: new Map(),
      }
      Effect.runSync(
        Ref.get(stateRef).pipe(
          Effect.map((s) => {
            state = s
          }),
        ),
      )
      return JSON.stringify({
        tokens: Object.fromEntries(
          [...state.tokens.entries()].map(([k, v]) => [
            k,
            { ...v, expiresOn: v.expiresOn.toISOString() },
          ]),
        ),
        accounts: Object.fromEntries(state.accounts.entries()),
      })
    },
    deserialize: (data: string) => {
      // biome-ignore lint/suspicious/noExplicitAny: JSON.parse returns unknown structure
      const parsed = JSON.parse(data) as any
      const tokens = new Map<string, CachedTokenEntry>(
        Object.entries(parsed.tokens ?? {}).map(([k, v]) => {
          // biome-ignore lint/suspicious/noExplicitAny: deserialized from JSON
          const entry = v as any
          return [
            k,
            {
              ...entry,
              expiresOn: new Date(entry.expiresOn),
              refreshToken: entry.refreshToken
                ? Option.some(entry.refreshToken as string)
                : Option.none(),
            } satisfies CachedTokenEntry,
          ]
        }),
      )
      const accounts = new Map<string, AccountCacheEntry>(
        Object.entries(parsed.accounts ?? {}).map(([k, v]) => [
          k,
          v as AccountCacheEntry,
        ]),
      )
      hasChanged = true
      Effect.runSync(Ref.set(stateRef, { tokens, accounts }))
    },
  }
}
