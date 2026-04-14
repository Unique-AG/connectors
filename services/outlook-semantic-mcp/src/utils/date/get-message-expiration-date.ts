import { startOfUtcDay } from './start-of-utc-day';

export const getMessageExpirationDate = ({
  receivedDateTime,
  retentionWindowInDays,
}: {
  receivedDateTime: string | Date;
  retentionWindowInDays: number;
}): Date => {
  // The expiration date is midnight UTC of (receivedDateTime + retentionWindowInDays + 1 day).
  // Using start-of-next-day (exclusive boundary) rather than 23:59:59.999 (inclusive) ensures
  // the timestamp survives API/DB round-trips intact: many DateTime implementations truncate
  // sub-second precision, which would cause 23:59:59.999 to drift and break equality checks.
  // Batching all emails to the same UTC midnight also keeps expiry consistent across a sync cycle.
  const expirationDate = new Date(receivedDateTime);
  expirationDate.setUTCDate(expirationDate.getUTCDate() + retentionWindowInDays + 1);
  return startOfUtcDay(expirationDate);
};
