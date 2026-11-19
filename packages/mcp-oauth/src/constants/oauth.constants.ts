export const OAUTH_ENDPOINTS = {
  authorize: '/auth/authorize',
  consent: '/auth/consent',
  callback: '/auth/callback',
  register: '/auth/register',
  token: '/auth/token',
  revoke: '/auth/revoke',
  introspect: '/auth/introspect',
};

/**
 * The paths an MCP client falls back to when it cannot read the authorization server metadata,
 * per the 2025-03-26 MCP authorization spec. Served as aliases so a client that lost discovery
 * still completes the flow instead of hitting a 404.
 */
export const OAUTH_FALLBACK_ENDPOINTS = {
  authorize: '/authorize',
  token: '/token',
  register: '/register',
};
