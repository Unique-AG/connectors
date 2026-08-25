import { beforeEach, describe, expect, it, vi } from 'vitest';
import { CalendarMetricsService } from '../calendar-metrics.service';
import { MetricName } from '../metric-names';

const record = vi.fn();
const getHistogram = vi.fn().mockReturnValue({ record });

describe(CalendarMetricsService.name, () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getHistogram.mockReturnValue({ record });
  });

  it('records duration with in-memory filter flags and the date-window bucket', async () => {
    const service = new CalendarMetricsService({ getHistogram } as never);

    await service.measureSearch(
      {
        dateWindow: '<1week',
        hasAttendeeFilter: true,
        hasSubjectFilter: false,
        hasCategoryFilter: true,
      },
      async () => ({ success: true }),
    );

    expect(getHistogram).toHaveBeenCalledWith(
      MetricName.SearchCalendarEventsDuration,
      expect.objectContaining({ description: expect.any(String) }),
    );
    expect(record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        hasAttendeeFilter: true,
        hasSubjectFilter: false,
        hasCategoryFilter: true,
        dateWindow: '<1week',
        status: 'success',
        functionRunResult: 'success',
      }),
    );
  });

  it('keeps the date-window label when the search itself returns failed', async () => {
    const service = new CalendarMetricsService({ getHistogram } as never);

    await service.measureSearch(
      {
        dateWindow: '<1month',
        hasAttendeeFilter: false,
        hasSubjectFilter: false,
        hasCategoryFilter: false,
      },
      async () => ({ success: false }),
    );

    expect(record).toHaveBeenCalledWith(
      expect.any(Number),
      expect.objectContaining({
        dateWindow: '<1month',
        status: 'failed',
        functionRunResult: 'success',
      }),
    );
  });
});
