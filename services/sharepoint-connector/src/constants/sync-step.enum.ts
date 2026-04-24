export const FullSyncStep = {
  SitesConfigLoading: 'sites_config_loading',
  Unknown: 'unknown',
} as const;

export type FullSyncStep = (typeof FullSyncStep)[keyof typeof FullSyncStep];

export const SiteSyncStep = {
  SiteNameFetch: 'site_name_fetch',
  RootScopeInit: 'root_scope_initialization',
  SubsiteDiscovery: 'subsite_discovery',
  SiteItemsFetch: 'site_items_fetch',
  SubsiteItemsFetch: 'subsite_items_fetch',
  ScopesCreation: 'scopes_creation',
  ContentSync: 'content_sync',
  PermissionsFetch: 'permissions_fetch',
  GroupsMembershipsFetch: 'groups_memberships_fetch',
  UniqueDataFetch: 'unique_data_fetch',
  GroupsSync: 'groups_sync',
  FilePermissionsSync: 'file_permissions_sync',
  FolderPermissionsSync: 'folder_permissions_sync',
  UnknownPermissionsSync: 'unknown_permissions_sync',
  StaleScopeCleanup: 'stale_scope_cleanup',
} as const;

export type SiteSyncStep = (typeof SiteSyncStep)[keyof typeof SiteSyncStep];
