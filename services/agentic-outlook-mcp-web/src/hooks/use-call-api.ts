import { useAuth } from 'react-oidc-context';

const backendUrl = import.meta.env.VITE_BACKEND_URL;

export const useCallApi = () => {
  const { user } = useAuth();

  function callApi<TResponse>(
    apiFunction: (options?: RequestInit) => Promise<TResponse>,
    options?: RequestInit,
  ): Promise<TResponse>;

  function callApi<TParams, TResponse>(
    apiFunction: (params: TParams, options?: RequestInit) => Promise<TResponse>,
    params: TParams,
    options?: RequestInit,
  ): Promise<TResponse>;

  async function callApi<TParams, TResponse>(
    apiFunction: ((options?: RequestInit) => Promise<TResponse>) | ((params: TParams, options?: RequestInit) => Promise<TResponse>),
    paramsOrOptions?: TParams | RequestInit,
    maybeOptions?: RequestInit,
  ): Promise<TResponse> {
    const { access_token } = user || {};
    if (!access_token) throw new Error('User not authenticated.');

    const isParamsProvided = apiFunction.length > 1;
    const params = isParamsProvided ? paramsOrOptions as TParams : undefined;
    const options = isParamsProvided ? maybeOptions : paramsOrOptions as RequestInit | undefined;

    const enrichedOptions: RequestInit = {
      ...options,
      headers: {
        ...options?.headers,
        Authorization: `Bearer ${access_token}`,
      },
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
      if (isParamsProvided) {
        return await (apiFunction as (params: TParams, options?: RequestInit) => Promise<TResponse>)(params as TParams, enrichedOptions);
      }
      return await (apiFunction as (options?: RequestInit) => Promise<TResponse>)(enrichedOptions);
    } finally {
      window.fetch = originalFetch;
    }
  }

  return { callApi };
};

