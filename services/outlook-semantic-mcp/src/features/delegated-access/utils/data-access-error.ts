import { isObjectType } from 'remeda';

export enum CannotReadErrorReason {
  TokenExpired = 'token-expired',
  TransientError = 'transient-error',
  UnexpectedError = 'unexpected-error',
}

export interface DataAccessError {
  canRead: false;
  reason: CannotReadErrorReason;
  error: unknown;
  // More error context if it happens for 1 folder we can pass the folder id
  folderId?: string;
}

export const isDataAccessError = (input: unknown): input is DataAccessError =>
  isObjectType(input) &&
  'canRead' in input &&
  input.canRead === false &&
  'reason' in input &&
  Object.values(CannotReadErrorReason).includes(input.reason as CannotReadErrorReason);
