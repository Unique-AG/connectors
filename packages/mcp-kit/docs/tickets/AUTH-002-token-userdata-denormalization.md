# AUTH-002: Token userData denormalization

## Summary
Denormalize user profile data (email, displayName) into `AccessTokenMetadata.userData` at token issuance time, so that `McpIdentityResolver` (defined in CORE-006) can build a complete `McpIdentity` from `request.user` without making a separate `IOAuthStore.getUserProfileById()` call at request time. This eliminates a DB round-trip per authenticated MCP request.

## Background / Context
Without denormalization, building `McpIdentity` at request time would require two steps: (1) validate the opaque token to get `TokenValidationResult`, and (2) fetch the user profile via `IOAuthStore.getUserProfileById(profileId)` to populate email/displayName. The design mandates that profile data is **denormalized into the token at issuance time** — stored in `AccessTokenMetadata.userData` — so `McpIdentityResolver` can build the full `McpIdentity` purely from `request.user`.

The `AccessTokenMetadata` interface (defined in AUTH-001) has a `userData` field. This ticket types it strictly, populates it during `generateTokenPair()`, and ensures `McpIdentityResolver` (CORE-006) reads from it.

## Acceptance Criteria

### Branded types (owned by this module)
- [ ] `UserProfileId = z.string().min(1).brand('UserProfileId')` — DB primary key for user profile records; prevents passing a `UserId` in a `UserProfileId` slot
- [ ] Exported from `auth/types.ts`

### Core functionality
- [ ] `TokenUserData` interface defined: `{ email?: string; displayName?: string }`
- [ ] `AccessTokenMetadata.userData` typed as `TokenUserData` (not `unknown`)
- [ ] `TokenValidationResult.userData` typed as `TokenUserData` (not `unknown`)
- [ ] `OpaqueTokenService.generateTokenPair()` calls `store.getUserProfileById(userProfileId)` to fetch email/displayName before calling `store.storeAccessToken()`
- [ ] The stored `AccessTokenMetadata` includes `userData: { email, displayName }` populated from the profile
- [ ] `OpaqueTokenService.validateAccessToken()` returns `TokenValidationResult` with `userData` populated from stored metadata
- [ ] `McpIdentityResolver` (CORE-006) builds `McpIdentity.email` and `McpIdentity.displayName` from `request.user.userData` without calling `IOAuthStore`
- [ ] Token refresh re-fetches `userData` from the profile store (to pick up any profile changes since original grant)
- [ ] `TokenUserData` is exported from `@unique-ag/nestjs-mcp/auth`
- [ ] CORE-006's `McpIdentity` interface includes `email?: string` and `displayName?: string` fields populated from `TokenValidationResult.userData`. If CORE-006 is implemented without these fields, AUTH-002 implementation must add them.

## BDD Scenarios

```gherkin
Feature: User profile data denormalized into access tokens

  Rule: Newly issued tokens include the user's profile data

    Scenario: Token issued for a user with a complete profile
      Given user "alice" has a profile with email "alice@example.com" and display name "Alice Smith"
      When a new access token is issued for "alice"
      Then the token contains email "alice@example.com" and display name "Alice Smith"

    Scenario: Token issued for a user with a partial profile
      Given user "charlie" has a profile with email "charlie@example.com" but no display name
      When a new access token is issued for "charlie"
      Then the token contains email "charlie@example.com" and no display name

    Scenario: Token issued when the user profile is missing
      Given user "unknown" has no profile in the store
      When a new access token is issued for "unknown"
      Then the token is still issued successfully
      And the token contains no email and no display name
      And a warning is logged about the missing profile

  Rule: Authenticated requests use token-embedded profile data without additional lookups

    Scenario: MCP identity is built from the token's embedded profile data
      Given a client authenticates with a token containing email "alice@example.com" and display name "Alice Smith"
      When a tool accesses the client's identity
      Then the identity email is "alice@example.com"
      And the identity display name is "Alice Smith"
      And no additional profile lookup is performed

    Scenario: Validating a token returns the embedded profile data
      Given an access token was issued with email "bob@example.com" and display name "Bob"
      When the token is validated
      Then the validation result includes email "bob@example.com" and display name "Bob"

  Rule: Token refresh picks up profile changes

    Scenario: Refreshed token reflects updated profile data
      Given user "bob" was issued a token with display name "Bob"
      And "bob" has since changed their display name to "Robert"
      When the token is refreshed
      Then the new token contains display name "Robert"

  Rule: Expired tokens are rejected regardless of embedded data

    Scenario: Expired token with profile data is rejected
      Given an access token was issued for user "dave" with email "dave@example.com"
      And the token has expired
      When the token is validated
      Then the validation fails
      And the expired token is cleaned up from the store
```

## Dependencies
- Depends on: AUTH-001 — `OpaqueTokenService`, `AccessTokenMetadata`, and `IOAuthStore` must be structured in the auth sub-entrypoint
- Depends on: CORE-006 — `McpIdentityResolver` must exist to consume `userData` from `request.user`. The `McpIdentity` interface defines `email` and `displayName` fields that this ticket populates.
- Blocks: None directly, but all downstream tools benefit from faster identity resolution

## Technical Notes

### TokenUserData interface
```typescript
// Exported from @unique-ag/nestjs-mcp/auth
export interface TokenUserData {
  email?: string;
  displayName?: string;
}
```

### Updated AccessTokenMetadata
```typescript
export interface AccessTokenMetadata {
  userId: string;
  clientId: string;
  scope: string;
  resource: string;
  expiresAt: Date;
  userProfileId: string;
  userData?: TokenUserData;  // was: unknown
}
```

### Updated TokenValidationResult
```typescript
export interface TokenValidationResult {
  userId: string;
  clientId: string;
  scope: string;
  resource: string;
  userProfileId: string;
  userData?: TokenUserData;  // was: unknown
}
```

### generateTokenPair() changes
```typescript
async generateTokenPair(
  userId: string, clientId: string, scope: string,
  resource: string, userProfileId: string,
  familyId?: string | null, generation?: number,
): Promise<TokenPair> {
  // Fetch profile to denormalize into token
  const profile = await this.store.getUserProfileById(userProfileId);
  const userData: TokenUserData = {
    email: profile?.email,
    displayName: profile?.display_name ?? profile?.displayName,
  };

  // ... generate token, then store with userData:
  await this.store.storeAccessToken(accessToken, {
    userId, clientId, scope, resource, expiresAt, userProfileId,
    userData,  // <-- NEW
  });
  // ...
}
```

### Cross-ticket interface contract
- **AUTH-002 produces**: `TokenValidationResult.userData` typed as `TokenUserData`
- **CORE-006 consumes**: `McpIdentityResolver` reads `request.user.userData.email` and `request.user.userData.displayName` to populate `McpIdentity.email` and `McpIdentity.displayName`
- The `McpIdentity` interface (CORE-006) has `email: string | undefined` and `displayName: string | undefined`
- `McpIdentityResolver` maps: `request.user.userData?.email -> McpIdentity.email`, `request.user.userData?.displayName -> McpIdentity.displayName`

### Design decision: Re-fetch on refresh vs carry forward
On token refresh, `userData` is re-fetched from the profile store (via a new `generateTokenPair()` call which calls `getUserProfileById()`). This ensures profile changes (e.g., user updated their display name) are reflected in new tokens. The cost is one additional DB call per refresh (infrequent), which is acceptable.

### Token refresh and userData staleness
When a token is refreshed (new access token issued), the `userData` denormalization is NOT re-run automatically. Denormalized fields reflect the state at original token issuance. If `email` or `displayName` changes upstream, the user must re-authenticate to get updated values in their session.

### SDK APIs used
No direct `@modelcontextprotocol/sdk` APIs are involved in this ticket. The denormalization is purely an application-layer optimization within the auth module.
