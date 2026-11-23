import type Dispatcher from 'undici/types/dispatcher';

export class HttpStatusError extends Error {
  public override readonly name = 'HttpStatusError';

  public constructor(
    public readonly statusCode: number,
    message: string,
  ) {
    super(message);
  }
}

// to extract into shared utils package
export async function handleErrorStatus(
  statusCode: number,
  responseBody: Dispatcher.BodyMixin,
  url: string,
): Promise<void> {
  if (statusCode < 200 || statusCode >= 300) {
    const errorText = await responseBody.text().catch(() => 'No response body');
    throw new HttpStatusError(statusCode, `Error response from ${url}: ${statusCode} ${errorText}`);
  }
}
