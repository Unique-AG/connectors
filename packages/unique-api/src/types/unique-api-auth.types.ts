export interface UniqueApiAuth {
  getToken(): Promise<string>;
}
