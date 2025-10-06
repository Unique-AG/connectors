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

  async function callApi<TParams, TResponse>(
    apiFunction:
      | ((options?: RequestInit) => Promise<TResponse>)
      | ((params: TParams, options?: RequestInit) => Promise<TResponse>),
    paramsOrOptions?: TParams | RequestInit,
    maybeOptions?: RequestInit,
  ): Promise<TResponse> {
    const { access_token } = user || {};
    if (!access_token) throw new Error('User not authenticated.');

    const isParamsProvided = apiFunction.length > 1;
    const params = isParamsProvided ? (paramsOrOptions as TParams) : undefined;
    const options = isParamsProvided ? maybeOptions : (paramsOrOptions as RequestInit | undefined);

    const enrichedOptions: RequestInit = {
      ...options,
      headers: {
        ...options?.headers,
        Authorization: `Bearer ${access_token}`,
      },
    };

    if (isParamsProvided)
      return (apiFunction as (params: TParams, options?: RequestInit) => Promise<TResponse>)(
        params as TParams,
        enrichedOptions,
      );
    return (apiFunction as (options?: RequestInit) => Promise<TResponse>)(enrichedOptions);
  }

  return { callApi };
};
