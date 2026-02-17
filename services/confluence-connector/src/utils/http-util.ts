import type Dispatcher from 'undici/types/dispatcher';

export async function handleErrorStatus(
  statusCode: number,
  responseBody: Dispatcher.BodyMixin,
  url: string,
): Promise<void> {
  if (statusCode < 200 || statusCode >= 300) {
    const errorText = await responseBody.text().catch(() => 'No response body');
    throw new Error(`Error response from ${url}: ${statusCode} ${errorText}`);
  }
}
