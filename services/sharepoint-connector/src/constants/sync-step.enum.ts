export const SyncStep = {
  SitesConfigLoading: 'sites_config_loading',
  RootScopeInit: 'root_scope_initialization',
  SiteNameFetch: 'site_name_fetch',
  SubsiteDiscovery: 'subsite_discovery',
  SiteItemsFetch: 'site_items_fetch',
  ScopesCreation: 'scopes_creation',
  ContentSync: 'content_sync',
  PermissionsSync: 'permissions_sync',
  PermissionsFetch: 'permissions_fetch',
  GroupsMembershipsFetch: 'groups_memberships_fetch',
  UniqueDataFetch: 'unique_data_fetch',
  GroupsSync: 'groups_sync',
  FilePermissionsSync: 'file_permissions_sync',
  FolderPermissionsSync: 'folder_permissions_sync',
  OrphanScopeCleanup: 'orphan_scope_cleanup',
  Unknown: 'unknown',
} as const;

export type SyncStep = (typeof SyncStep)[keyof typeof SyncStep];
