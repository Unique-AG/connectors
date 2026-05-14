import { AggregationType, InstrumentType } from '@unique-ag/instrumentation';
import { SyncMetricName } from './sync-metrics.service';

export const syncMetricViews = [
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.FullSyncRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [5, 15, 30, 60, 120, 300, 600, 900] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.FullSyncBatchDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120, 300] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.FullSyncDirectorySyncDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [0.1, 0.5, 1, 2, 5, 10, 30] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.LiveCatchupRunDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120, 300] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.LiveCatchupDirectorySyncDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [0.1, 0.5, 1, 2, 5, 10, 30] },
    },
  },
  {
    instrumentType: InstrumentType.HISTOGRAM,
    instrumentName: SyncMetricName.LiveCatchupBatchDuration,
    aggregation: {
      type: AggregationType.EXPLICIT_BUCKET_HISTOGRAM,
      options: { boundaries: [1, 5, 10, 30, 60, 120, 300] },
    },
  },
];
