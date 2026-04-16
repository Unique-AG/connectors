export const startOfUtcDay = (date: Date): Date => {
  const out = new Date(date);
  out.setUTCHours(0, 0, 0, 0);
  return out;
};
