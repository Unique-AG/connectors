import { WebStorageStateStore } from 'oidc-client-ts';
import { type AuthProviderProps } from 'react-oidc-context';

const getOidcConfig = (): AuthProviderProps => {
  const backendUrl = import.meta.env.VITE_BACKEND_URL;
  const clientId = import.meta.env.VITE_OAUTH_CLIENT_ID;
  const redirectUri = `${window.location.origin}/callback`;
  const postLogoutRedirectUri = `${window.location.origin}/`;

  return {
    authority: backendUrl,
    client_id: clientId,
    redirect_uri: redirectUri,
    post_logout_redirect_uri: postLogoutRedirectUri,
    response_type: 'code',
    scope: 'openid profile email offline_access',

    automaticSilentRenew: true,
    loadUserInfo: false,

    userStore: new WebStorageStateStore({ store: window.localStorage }),

    extraQueryParams: {
      resource: `${backendUrl}/mcp`,
    },

    onSigninCallback: () => {
      window.history.replaceState({}, document.title, window.location.pathname);
    },
  };
};

export default getOidcConfig;
