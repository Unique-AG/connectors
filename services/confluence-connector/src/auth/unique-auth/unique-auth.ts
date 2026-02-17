export abstract class UniqueAuth {
  public abstract getHeaders(): Promise<Record<string, string>>;
}
