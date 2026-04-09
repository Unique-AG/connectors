export const getExpirationDate = ({
  receivedDateTime,
  retentionWindowInDays,
}: {
  receivedDateTime: string | Date;
  retentionWindowInDays: number;
}): Date => {
  // End of utc day.
  const currentReceivedAt = new Date(receivedDateTime);
  currentReceivedAt.setUTCHours(0, 0, 0, 0);
  currentReceivedAt.setDate(currentReceivedAt.getDate() + retentionWindowInDays + 1);
  currentReceivedAt.setMilliseconds(-1);
  return currentReceivedAt;
};
