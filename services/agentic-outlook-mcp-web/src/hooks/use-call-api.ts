import { useAuth } from 'react-oidc-context';

const backendUrl = import.meta.env.VITE_BACKEND_URL;

export const useCallApi = () => {
  const { user } = useAuth();

  const callApi = async <TResponse>(
    apiFunction: (options?: RequestInit) => Promise<TResponse>,
    options?: RequestInit,
  ): Promise<TResponse> => {
    const { access_token } = user || {};
    if (!access_token) throw new Error('User not authenticated.');

    const headers = new Headers(options?.headers);
    headers.set('Authorization', `Bearer ${access_token}`);

    const enrichedOptions: RequestInit = {
      ...options,
      headers,
    };

    const originalFetch = window.fetch;
    window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      let url: string;

      if (typeof input === 'string') {
        url = input;
      } else if (input instanceof URL) {
        url = input.toString();
      } else {
        url = input.url;
      }

      if (url.startsWith('/')) {
        url = `${backendUrl}${url}`;
      }

      return originalFetch(url, init);
    };

    try {
      return await apiFunction(enrichedOptions);
    } finally {
      window.fetch = originalFetch;
    }
  };

  return { callApi };
};

