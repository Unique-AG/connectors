import { Option } from 'effect';

export interface TokenCachePlugin {
  readonly beforeCacheAccess: (cache: TokenCacheContext) => Promise<void> | void;
  readonly afterCacheAccess: (cache: TokenCacheContext) => Promise<void> | void;
}

export interface TokenCacheContext {
  readonly cacheHasChanged: boolean;
  readonly serialize: () => string;
  readonly deserialize: (data: string) => void;
}

export interface CachedTokenEntry {
  readonly accessToken: string;
  readonly expiresOn: Date;
  readonly scopes: ReadonlyArray<string>;
  readonly refreshToken: Option.Option<string>;
  readonly accountId: string;
}

export interface TokenCacheState {
  readonly tokens: ReadonlyMap<string, CachedTokenEntry>;
  readonly accounts: ReadonlyMap<string, AccountCacheEntry>;
}

export interface AccountCacheEntry {
  readonly homeAccountId: string;
  readonly localAccountId: string;
  readonly username: string;
  readonly tenantId: string;
  readonly name: string | null;
}
