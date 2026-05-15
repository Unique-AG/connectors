export interface UniqueAuthFacade {
  getToken(): Promise<string>;
  getAuthHeaders(): Promise<Record<string, string>>;
}
