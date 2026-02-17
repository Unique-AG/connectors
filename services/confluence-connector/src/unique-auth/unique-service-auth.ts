export abstract class UniqueServiceAuth {
  public abstract getHeaders(): Promise<Record<string, string>>;
}
