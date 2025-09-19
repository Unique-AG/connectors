import { User, WebStorageStateStore } from 'oidc-client-ts';
import { type AuthProviderProps } from 'react-oidc-context';

const getOidcConfig = (): AuthProviderProps => {
  const backendUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:3000';
  const clientId = import.meta.env.VITE_OAUTH_CLIENT_ID || 'agentic-outlook-mcp-web';
  const redirectUri = `${window.location.origin}/callback`;
  const postLogoutRedirectUri = `${window.location.origin}/`;
  
  return {
    authority: backendUrl,
    client_id: clientId,
    redirect_uri: redirectUri,
    post_logout_redirect_uri: postLogoutRedirectUri,
    response_type: 'code',
    scope: 'openid profile email offline_access',
    
    // PKCE is required by the backend (OAuth 2.1)
    automaticSilentRenew: true,
    loadUserInfo: false, // Backend may not provide userinfo endpoint
    
    // Store tokens in localStorage for persistence
    userStore: new WebStorageStateStore({ store: window.localStorage }),
    
    metadata: {
      // Override metadata endpoints since backend uses custom paths
      issuer: backendUrl,
      authorization_endpoint: `${backendUrl}/auth/authorize`,
      token_endpoint: `${backendUrl}/auth/token`,
      revocation_endpoint: `${backendUrl}/auth/revoke`,
      introspection_endpoint: `${backendUrl}/auth/introspect`,
      end_session_endpoint: `${backendUrl}/auth/logout`,
    },
    
    // Resource parameter for RFC 8707 compliance
    extraQueryParams: {
      resource: `${backendUrl}/mcp`,
    },
    
    onSigninCallback: () => {
      // Remove OIDC params from URL after successful login
      window.history.replaceState({}, document.title, window.location.pathname);
    },
  };
};

export default getOidcConfig;

export const mapOidcUserToAppUser = (user: User | null) => {
  if (!user) return null;
  
  return {
    id: user.profile.sub || '',
    email: user.profile.email || '',
    name: user.profile.name || user.profile.preferred_username || '',
    accessToken: user.access_token,
    refreshToken: user.refresh_token,
  };
};
