export interface GraphAuthStrategy {
  getAccessToken(scope: string): Promise<string>;
}
