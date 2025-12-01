import { Module } from '@nestjs/common';
import { ValueType } from '@opentelemetry/api';
import { MetricService } from 'nestjs-otel';
import {
  SPC_FILE_DELETED_TOTAL,
  SPC_FILE_DIFF_EVENTS_TOTAL,
  SPC_FILE_MOVED_TOTAL,
  SPC_INGESTION_FILE_PROCESSED_TOTAL,
  SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
  SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
  SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
  SPC_PERMISSIONS_SYNC_DURATION_SECONDS,
  SPC_PERMISSIONS_SYNC_FILE_OPERATIONS_TOTAL,
  SPC_PERMISSIONS_SYNC_FOLDER_OPERATIONS_TOTAL,
  SPC_PERMISSIONS_SYNC_GROUP_OPERATIONS_TOTAL,
  SPC_SYNC_DURATION_SECONDS,
  SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
  SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
  SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS,
  SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL,
} from './metrics.tokens';
import { REQUEST_DURATION_BUCKET_BOUNDARIES } from './utils';

@Module({
  providers: [
    {
      provide: SPC_SYNC_DURATION_SECONDS,
      useFactory: (metricService: MetricService) => {
        return metricService.getHistogram('spc_sync_duration_seconds', {
          description: 'Duration of SharePoint synchronization cycles (per site and full sync)',
          valueType: ValueType.DOUBLE,
          advice: {
            explicitBucketBoundaries: [10, 30, 60, 300, 600, 1800, 3600],
          },
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_INGESTION_FILE_PROCESSED_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_ingestion_file_processed_total', {
          description: 'Number of files processed by ingestion pipeline steps',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
      useFactory: (metricService: MetricService) => {
        return metricService.getHistogram('spc_ms_graph_api_request_duration_seconds', {
          description: 'Request latency for Microsoft Graph API calls',
          valueType: ValueType.DOUBLE,
          advice: {
            explicitBucketBoundaries: REQUEST_DURATION_BUCKET_BOUNDARIES,
          },
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_ms_graph_api_throttle_events_total', {
          description: 'Number of Microsoft Graph API throttling events',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_ms_graph_api_slow_requests_total', {
          description: 'Number of slow Microsoft Graph API requests',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
      useFactory: (metricService: MetricService) => {
        return metricService.getHistogram('spc_unique_graphql_api_request_duration_seconds', {
          description: 'Request latency for Unique GraphQL API calls',
          valueType: ValueType.DOUBLE,
          advice: {
            explicitBucketBoundaries: REQUEST_DURATION_BUCKET_BOUNDARIES,
          },
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_unique_graphql_api_slow_requests_total', {
          description: 'Number of slow Unique GraphQL API calls',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS,
      useFactory: (metricService: MetricService) => {
        return metricService.getHistogram('spc_unique_rest_api_request_duration_seconds', {
          description: 'Request latency for Unique REST API calls',
          valueType: ValueType.DOUBLE,
          advice: {
            explicitBucketBoundaries: REQUEST_DURATION_BUCKET_BOUNDARIES,
          },
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_unique_rest_api_slow_requests_total', {
          description: 'Number of slow Unique REST API calls',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_FILE_MOVED_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_file_moved_total', {
          description: 'Number of file move operations in Unique',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_FILE_DIFF_EVENTS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_file_diff_events_total', {
          description: 'Number of file change detection events (new, updated, moved, deleted)',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_FILE_DELETED_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_file_deleted_total', {
          description: 'Number of file deletion operations in Unique',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_PERMISSIONS_SYNC_DURATION_SECONDS,
      useFactory: (metricService: MetricService) => {
        return metricService.getHistogram('spc_permissions_sync_duration_seconds', {
          description: 'Duration of the permissions synchronization phase for a site',
          valueType: ValueType.DOUBLE,
          advice: {
            explicitBucketBoundaries: [5, 10, 30, 60, 120, 300, 600, 1800],
          },
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_PERMISSIONS_SYNC_GROUP_OPERATIONS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_permissions_sync_group_operations_total', {
          description:
            'Number of operations performed on SharePoint groups during permissions sync',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_PERMISSIONS_SYNC_FOLDER_OPERATIONS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_permissions_sync_folder_operations_total', {
          description: 'Number of folder (scope) permission changes synced',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
    {
      provide: SPC_PERMISSIONS_SYNC_FILE_OPERATIONS_TOTAL,
      useFactory: (metricService: MetricService) => {
        return metricService.getCounter('spc_permissions_sync_file_operations_total', {
          description: 'Number of permissions changing operations performed on Unique files',
          valueType: ValueType.INT,
        });
      },
      inject: [MetricService],
    },
  ],
  exports: [
    SPC_SYNC_DURATION_SECONDS,
    SPC_INGESTION_FILE_PROCESSED_TOTAL,
    SPC_MS_GRAPH_API_REQUEST_DURATION_SECONDS,
    SPC_MS_GRAPH_API_THROTTLE_EVENTS_TOTAL,
    SPC_MS_GRAPH_API_SLOW_REQUESTS_TOTAL,
    SPC_UNIQUE_GRAPHQL_API_REQUEST_DURATION_SECONDS,
    SPC_UNIQUE_GRAPHQL_API_SLOW_REQUESTS_TOTAL,
    SPC_UNIQUE_REST_API_REQUEST_DURATION_SECONDS,
    SPC_UNIQUE_REST_API_SLOW_REQUESTS_TOTAL,
    SPC_FILE_MOVED_TOTAL,
    SPC_FILE_DIFF_EVENTS_TOTAL,
    SPC_FILE_DELETED_TOTAL,
    SPC_PERMISSIONS_SYNC_DURATION_SECONDS,
    SPC_PERMISSIONS_SYNC_GROUP_OPERATIONS_TOTAL,
    SPC_PERMISSIONS_SYNC_FOLDER_OPERATIONS_TOTAL,
    SPC_PERMISSIONS_SYNC_FILE_OPERATIONS_TOTAL,
  ],
})
export class MetricsModule {}
