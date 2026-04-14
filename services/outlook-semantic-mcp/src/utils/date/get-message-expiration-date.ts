export const getMessageExpirationDate = ({
  receivedDateTime,
  retentionWindowInDays,
}: {
  receivedDateTime: string | Date;
  retentionWindowInDays: number;
}): Date => {
  // The expiration date is end of day receivedDateTime + retentionWindowInDays we set it like this
  // to have concistency when a batch of emails expire otherwise during the day things will start
  // to dissapear from searches, like this at end of UTC day all emails expire.
  const expirationDate = new Date(receivedDateTime);
  expirationDate.setUTCDate(expirationDate.getUTCDate() + retentionWindowInDays);
  expirationDate.setUTCHours(23, 59, 59, 999);
  return expirationDate;
};
