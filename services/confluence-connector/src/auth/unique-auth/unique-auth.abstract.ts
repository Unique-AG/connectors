//We use abstract classes as service tokens because interfaces are erased at runtime and cannot be used as ServiceRegistry keys.
export abstract class UniqueAuth {
  public abstract getHeaders(): Promise<Record<string, string>>;
}
