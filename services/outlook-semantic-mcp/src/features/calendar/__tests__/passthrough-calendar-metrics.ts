import type { CalendarMetricsService } from '~/features/metrics/calendar-metrics.service';

export function passthroughCalendarMetrics(): Pick<
  CalendarMetricsService,
  'measureOperation' | 'measureSearch'
> {
  return {
    measureSearch: (_labels, fn) => fn(),
    measureOperation: (_labels, fn) => fn(),
  };
}
