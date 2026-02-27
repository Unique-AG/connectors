//We use abstract classes as service tokens because interfaces are erased at runtime and cannot be used as ServiceRegistry keys.
export abstract class ConfluenceAuth {
  public abstract acquireToken(): Promise<string>;
}
