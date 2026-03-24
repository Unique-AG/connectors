export function getHttpStatusCodeClass(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) {
    return '2xx';
  }
  if (statusCode >= 300 && statusCode < 400) {
    return '3xx';
  }
  // Report 4xx codes individually — they carry specific diagnostic meaning.
  if (statusCode >= 400 && statusCode < 500) {
    return statusCode.toString();
  }
  if (statusCode >= 500) {
    return '5xx';
  }
  return 'unknown';
}
