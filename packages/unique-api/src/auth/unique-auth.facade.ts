export interface UniqueAuthFacade {
  getToken(): Promise<string>;
}
