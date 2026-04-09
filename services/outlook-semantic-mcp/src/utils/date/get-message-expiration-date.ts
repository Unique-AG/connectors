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
  currentReceivedAt.setUTCDate(currentReceivedAt.getUTCDate() + retentionWindowInDays + 1);
  currentReceivedAt.setUTCMilliseconds(-1);
  return currentReceivedAt;
};
