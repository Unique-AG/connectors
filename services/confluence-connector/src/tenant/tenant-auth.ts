export abstract class TenantAuth {
  public abstract getAccessToken(): Promise<string>;
}
