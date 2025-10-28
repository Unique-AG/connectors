export interface AuthStrategy {
  getAccessToken(): Promise<string>;
}
