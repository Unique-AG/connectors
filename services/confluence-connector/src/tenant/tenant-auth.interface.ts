export interface TenantAuth {
  getAccessToken(): Promise<string>;
}
