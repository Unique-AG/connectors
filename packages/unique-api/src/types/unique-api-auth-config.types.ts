export interface ClusterLocalAuthConfig {
  mode: 'cluster_local';
  serviceId: string;
  extraHeaders: Record<string, string>;
}

export interface ExternalAuthConfig {
  mode: 'external';
  zitadelOauthTokenUrl: string;
  zitadelClientId: string;
  zitadelClientSecret: string;
  zitadelProjectId: string;
}

export type UniqueApiClientAuthConfig = ClusterLocalAuthConfig | ExternalAuthConfig;
