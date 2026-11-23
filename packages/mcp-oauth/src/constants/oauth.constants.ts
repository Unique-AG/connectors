export const OAUTH_ENDPOINTS = {
  authorize: '/auth/authorize',
  consent: '/auth/consent',
  callback: '/auth/callback',
  register: '/auth/register',
  token: '/auth/token',
  revoke: '/auth/revoke',
  introspect: '/auth/introspect',
};

/** MCP 2025-03-26 fallback paths. Clients use these when they cannot read the metadata. */
export const OAUTH_FALLBACK_ENDPOINTS = {
  authorize: '/authorize',
  token: '/token',
  register: '/register',
};
