export abstract class UniqueServiceAuth {
  public abstract getHeaders(): Promise<Record<string, string>>;

  public async close(): Promise<void> {
    // No-op by default; strategies with resources (e.g., undici Agent) override this.
  }
}
