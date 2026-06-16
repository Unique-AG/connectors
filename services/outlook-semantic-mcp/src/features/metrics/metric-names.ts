export enum MetricName {
  // Full sync
  FullSyncRunDuration = 'osm_full_sync_run_duration_seconds',
  FullSyncDirectorySyncDuration = 'osm_full_sync_directory_sync_duration_seconds',
  FullSyncBatchDuration = 'osm_full_sync_batch_duration_seconds',
  FullSyncGraphPageDuration = 'osm_full_sync_graph_page_duration_seconds',
  FullSyncProcessEmailDuration = 'osm_full_sync_process_email_duration_seconds',
  // Live catch-up
  LiveCatchupRunDuration = 'osm_live_catchup_run_duration_seconds',
  LiveCatchupRoundDuration = 'osm_live_catchup_round_duration_seconds',
  LiveCatchupDirectorySyncDuration = 'osm_live_catchup_directory_sync_duration_seconds',
  LiveCatchupBatchDuration = 'osm_live_catchup_batch_duration_seconds',
  LiveCatchupProcessEmailDuration = 'osm_live_catchup_process_email_duration_seconds',
  // Delegated access discovery
  DiscoverDelegatedAccessRunDuration = 'osm_discover_delegated_access_run_duration_seconds',
  DiscoverDelegatedAccessUserDuration = 'osm_discover_delegated_access_user_duration_seconds',
  // Delegated access verification
  SyncDelegatedAccessForAllUsersRunDuration = 'osm_sync_delegated_access_for_all_users_run_duration_seconds',
  SyncDelegatedAccessRunDuration = 'osm_sync_delegated_access_run_duration_seconds',
}
