export abstract class ConfluenceAuth {
  public abstract acquireToken(): Promise<string>;
}
