import { GraphError } from '@microsoft/microsoft-graph-client';
import { isObjectType } from 'remeda';

export const isDelegatedAccessNotAvailableError = (error: unknown): boolean =>
  (error instanceof GraphError &&
    // Read / View access does not exist -> Ms graph returns 404 / 403 status codes for that
    (error.statusCode === 404 ||
      error.statusCode === 403 ||
      // The mailbox is not mapped in the exchange, this normally does should not happen if the
      // deployment handles 1 tenant, but in Unique we have 2 tenants: Dogfood and Unique and when
      // a email nicolae.bacila@unique.ai is cross referenced to nicolae.bacila@dogfood.industries
      // we get a error from exchange that 'nicolae.bacila@dogfood.industries' is stale
      error.code === 'MailboxInfoStale')) ||
  (isObjectType(error) && 'code' in error && error.code === 'MailboxInfoStale');

export const getDelegatedAccessErrorInfo = (
  error: unknown,
): Partial<{ statusCode: unknown; code: unknown }> => {
  const output: Partial<{ statusCode: unknown; code: unknown }> = {};
  if (isObjectType(error)) {
    if ('statusCode' in error) {
      output.statusCode = error.statusCode;
    }
    if ('code' in error) {
      output.code = error.code;
    }
  }
  return output;
};
