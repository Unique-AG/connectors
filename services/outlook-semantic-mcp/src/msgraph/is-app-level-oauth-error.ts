const APP_LEVEL_OAUTH_ERROR_CODES = new Set(['invalid_client', 'unauthorized_client']);

const extractOAuthErrorCode = (error: unknown): string | undefined => {
  if (typeof error === 'string') {
    return error;
  }
  if (typeof error !== 'object' || error === null) {
    return undefined;
  }
  if ('error' in error && typeof error.error === 'string') {
    return error.error;
  }
  return undefined;
};

export const isAppLevelOAuthError = (error: unknown): boolean => {
  const code = extractOAuthErrorCode(error);
  return code !== undefined && APP_LEVEL_OAUTH_ERROR_CODES.has(code);
};
