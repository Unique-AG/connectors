export {};

declare global {
  namespace Temporal {
    interface DurationLike {
      years?: number;
      months?: number;
      weeks?: number;
      days?: number;
      hours?: number;
      minutes?: number;
      seconds?: number;
      milliseconds?: number;
    }

    interface ToStringOptions {
      timeZoneName?: 'auto' | 'never' | 'critical';
      smallestUnit?: 'minute' | 'second' | 'millisecond';
    }

    interface ZonedDateTimeFields {
      year?: number;
      month?: number;
      day?: number;
      hour?: number;
      minute?: number;
      second?: number;
      millisecond?: number;
    }

    class Instant {
      public static from(item: string): Instant;
      public toZonedDateTimeISO(timeZone: string): ZonedDateTime;
    }

    class ZonedDateTime {
      public static from(item: string): ZonedDateTime;
      public readonly year: number;
      public readonly month: number;
      public readonly day: number;
      public readonly hour: number;
      public readonly minute: number;
      public readonly dayOfWeek: number;
      public readonly daysInMonth: number;
      public readonly offset: string;
      public startOfDay(): ZonedDateTime;
      public add(duration: DurationLike): ZonedDateTime;
      public subtract(duration: DurationLike): ZonedDateTime;
      public with(fields: ZonedDateTimeFields): ZonedDateTime;
      public toString(options?: ToStringOptions): string;
    }

    const Now: {
      instant(): Instant;
      zonedDateTimeISO(timeZone?: string): ZonedDateTime;
    };
  }
}
