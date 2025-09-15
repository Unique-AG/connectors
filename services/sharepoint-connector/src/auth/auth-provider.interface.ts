export interface IAuthProvider {
  getToken: (forceRefresh?: boolean) => Promise<string>;
}
