export type AbstractClass<T> = abstract new (...args: unknown[]) => T;

export class TenantServiceRegistry {
  // biome-ignore lint/complexity/noBannedTypes: Function is used as a map key for abstract class constructors
  private readonly map = new Map<Function, unknown>();

  public set<T>(key: AbstractClass<T>, instance: T): this {
    this.map.set(key, instance);
    return this;
  }

  public get<T>(key: AbstractClass<T>): T {
    if (!this.map.has(key)) {
      throw new Error(`Service not found in tenant registry: ${key.name}`);
    }
    return this.map.get(key) as T;
  }

  public has<T>(key: AbstractClass<T>): boolean {
    return this.map.has(key);
  }
}
