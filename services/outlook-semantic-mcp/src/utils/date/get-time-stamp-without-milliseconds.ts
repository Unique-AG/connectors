export const getTimeStampWithoutMilliseconds = (date: Date) => {
  return date.getTime() / 1000;
};
