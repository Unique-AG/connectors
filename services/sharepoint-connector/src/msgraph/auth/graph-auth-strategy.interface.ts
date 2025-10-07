export interface GraphAuthStrategy {
  getAccessToken(): Promise<string>;
}
