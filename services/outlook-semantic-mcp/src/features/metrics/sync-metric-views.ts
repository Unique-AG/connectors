import { AggregationType, InstrumentType, ViewOptions } from '@unique-ag/instrumentation';
import { MetricName } from './metric-names';

export const syncMetricViews: ViewOptions[] = [
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.FullSyncRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [3, 5, 15, 30, 60, 120] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.FullSyncBatchDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.FullSyncDirectorySyncDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [0.1, 0.5, 1, 2, 5, 10, 30] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.LiveCatchupRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 3, 5, 10, 15, 30, 60, 120] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.LiveCatchupDirectorySyncDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [0.1, 0.5, 1, 2, 5, 10, 30] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.LiveCatchupBatchDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120] },
    },
  },
  // Delegated access
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.DiscoverDelegatedAccessRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [30, 60, 120, 300, 600, 1200, 1800] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.DiscoverDelegatedAccessUserDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120, 300] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.SyncDelegatedAccessForAllUsersRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [30, 60, 120, 300, 600, 1200, 1800] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: MetricName.SyncDelegatedAccessRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [0.5, 1, 2, 5, 10, 30, 60] },
    },
  },
];
