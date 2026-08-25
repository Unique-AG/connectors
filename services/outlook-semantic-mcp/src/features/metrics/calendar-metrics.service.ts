import { Injectable } from '@nestjs/common';
import type { Histogram } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import type { DateWindowBucket } from '~/features/calendar/utils/date-window-bucket';
import { MetricName } from './metric-names';
import { recordInHistogram } from './record-in-histogram';

export interface CalendarSearchMetricLabels {
  dateWindow: DateWindowBucket;
  hasAttendeeFilter: boolean;
  hasSubjectFilter: boolean;
  hasCategoryFilter: boolean;
}

interface CalendarSearchMetricResult {
  success: boolean;
}

@Injectable()
export class CalendarMetricsService {
  private readonly searchDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.searchDuration = metricService.getHistogram(MetricName.SearchCalendarEventsDuration, {
      description:
        'Wall-clock duration of search_calendar_events in seconds, labelled by date-window size and in-memory filters',
    });
  }

  public measureSearch<T extends CalendarSearchMetricResult>(
    labels: CalendarSearchMetricLabels,
    fn: () => Promise<T>,
  ): Promise<T> {
    return recordInHistogram({
      histogram: this.searchDuration,
      attributes: {
        dateWindow: labels.dateWindow,
        hasAttendeeFilter: labels.hasAttendeeFilter,
        hasSubjectFilter: labels.hasSubjectFilter,
        hasCategoryFilter: labels.hasCategoryFilter,
      },
      successAttributes: (result) => ({
        status: result.success ? 'success' : 'failed',
      }),
      errorAttributes: () => ({
        status: 'failed',
      }),
      fn,
    });
  }
}
