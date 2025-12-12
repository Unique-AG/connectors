import { useAuth } from 'react-oidc-context';

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

  function callApi<TParams extends unknown[], TResponse>(
    apiFunction: (...args: [...TParams, RequestInit?]) => Promise<TResponse>,
    params: TParams,
    options?: RequestInit,
  ): Promise<TResponse>;

  async function callApi<TParams, TResponse>(
    apiFunction:
      | ((options?: RequestInit) => Promise<TResponse>)
      | ((params: TParams, options?: RequestInit) => Promise<TResponse>)
      | ((...args: unknown[]) => Promise<TResponse>),
    paramsOrOptions?: TParams | RequestInit | unknown[],
    maybeOptions?: RequestInit,
  ): Promise<TResponse> {
    const { access_token } = user || {};
    if (!access_token) throw new Error('User not authenticated.');

    const isParamsProvided = apiFunction.length > 1;
    const params = isParamsProvided ? paramsOrOptions : undefined;
    const options = isParamsProvided ? maybeOptions : (paramsOrOptions as RequestInit | undefined);

    const enrichedOptions: RequestInit = {
      ...options,
      headers: {
        ...options?.headers,
        Authorization: `Bearer ${access_token}`,
      },
    };

    if (isParamsProvided) {
      if (Array.isArray(params)) {
        return (apiFunction as (...args: unknown[]) => Promise<TResponse>)(
          ...params,
          enrichedOptions,
        );
      }
      return (apiFunction as (params: TParams, options?: RequestInit) => Promise<TResponse>)(
        params as TParams,
        enrichedOptions,
      );
    }
    return (apiFunction as (options?: RequestInit) => Promise<TResponse>)(enrichedOptions);
  }

  return { callApi };
};
