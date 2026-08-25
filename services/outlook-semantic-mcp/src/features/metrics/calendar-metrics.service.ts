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

export type CalendarOperation =
  | 'list_calendars'
  | 'check_availability'
  | 'suggest_meeting_times'
  | 'create_event'
  | 'update_event'
  | 'cancel_event'
  | 'respond_to_invite';

export type CalendarMetricErrorType =
  | 'consent'
  | 'not_found'
  | 'permission'
  | 'invalid'
  | 'too_many_entries'
  | 'other';

interface CalendarSearchMetricResult {
  success: boolean;
}

interface CalendarOperationMetricResult {
  success: boolean;
}

@Injectable()
export class CalendarMetricsService {
  private readonly searchDuration: Histogram;
  private readonly operationDuration: Histogram;

  public constructor(metricService: MetricService) {
    this.searchDuration = metricService.getHistogram(MetricName.SearchCalendarEventsDuration, {
      description:
        'Wall-clock duration of search_calendar_events in seconds, labelled by date-window size and in-memory filters',
    });
    this.operationDuration = metricService.getHistogram(MetricName.CalendarOperationDuration, {
      description:
        'Wall-clock duration of a calendar query or write command in seconds, excluding elicit confirmation',
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

  public measureOperation<T extends CalendarOperationMetricResult>(
    labels: {
      operation: CalendarOperation;
      dateWindow?: DateWindowBucket;
    },
    fn: (fail: (errorType: CalendarMetricErrorType) => void) => Promise<T>,
  ): Promise<T> {
    let errorType: CalendarMetricErrorType | undefined;
    return recordInHistogram({
      histogram: this.operationDuration,
      attributes: {
        operation: labels.operation,
        ...(labels.dateWindow !== undefined ? { dateWindow: labels.dateWindow } : {}),
      },
      successAttributes: (result) =>
        result.success
          ? { status: 'success' }
          : { status: 'failed', errorType: errorType ?? 'other' },
      errorAttributes: () => ({
        status: 'failed',
        errorType: errorType ?? 'other',
      }),
      fn: () =>
        fn((type) => {
          errorType = type;
        }),
    });
  }
}
