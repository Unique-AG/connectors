export const subUtcDays = (input: Date, days: number): Date => {
  const date = new Date(input);
  date.setUTCDate(date.getUTCDate() - days);
  return date;
};
