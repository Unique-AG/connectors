const getBody = <T>(c: Response | Request): Promise<T> => {
  const contentType = c.headers.get('content-type');

  if (contentType?.includes('application/json')) {
    return c.json();
  }

  if (contentType?.includes('application/pdf')) {
    return c.blob() as Promise<T>;
  }

  return c.text() as Promise<T>;
};

export const customFetch = async <T>(url: string, options: RequestInit): Promise<T> => {
  const requestUrl = `${import.meta.env.VITE_BACKEND_URL}${url}`;

  const response = await fetch(requestUrl, options);
  const data = await getBody<T>(response);

  return { status: response.status, data, headers: response.headers } as T;
};
