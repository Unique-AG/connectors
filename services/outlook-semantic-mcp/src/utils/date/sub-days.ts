export const subDays = (input: Date, days: number): Date => {
  const date = new Date(input);
  date.setDate(date.getDate() - days);
  return date;
};
