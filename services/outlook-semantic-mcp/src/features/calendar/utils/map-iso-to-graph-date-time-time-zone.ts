import { Temporal } from 'temporal-polyfill';

export function mapIsoToGraphDateTimeTimeZone(input: {
  iso: string;
  ianaTimeZone: string;
  windowsTimeZone: string;
}): { dateTime: string; timeZone: string } {
  const zoned = Temporal.Instant.from(input.iso).toZonedDateTimeISO(input.ianaTimeZone);
  return {
    dateTime: zoned.toPlainDateTime().toString({ smallestUnit: 'second' }),
    timeZone: input.windowsTimeZone,
  };
}
