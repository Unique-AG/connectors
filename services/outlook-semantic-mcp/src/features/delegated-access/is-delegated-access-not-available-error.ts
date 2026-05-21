import { GraphError } from '@microsoft/microsoft-graph-client';

export const isDelegatedAccessNotAvailableError = (error: unknown): error is GraphError =>
  error instanceof GraphError &&
  // Read / View access does not exist -> Ms graph returns 404 / 403 status codes for that
  (error.statusCode === 404 ||
    error.statusCode === 403 ||
    // The mailbox is not mapped in the exchange, this normally does should not happen if the
    // deployment handles 1 tenant, but in Unique we have 2 tenants: Dogfood and Unique and when
    // a email nicolae.bacila@unique.ai is cross referenced to nicolae.bacila@dogfood.industries
    // we get a error from exchange that 'nicolae.bacila@dogfood.industries' is stale
    error.code === 'MailboxInfoStale');
