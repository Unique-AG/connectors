# Future Idea: ASL-aware DI via Proxy Pattern

Downstream services inject a singleton proxy that delegates to the per-tenant instance via AsyncLocalStorage at call-time.

## Example

```typescript
// Abstract class doubles as NestJS DI token
abstract class UniqueServiceAuth {
  abstract getHeaders(): Promise<Record<string, string>>;
}

// Singleton proxy — reads current tenant from ASL
@Injectable()
class UniqueServiceAuthProxy extends UniqueServiceAuth {
  async getHeaders(): Promise<Record<string, string>> {
    return getCurrentTenant().uniqueAuth.getHeaders();
  }
}

// NestJS registration
providers: [
  { provide: UniqueServiceAuth, useClass: UniqueServiceAuthProxy }
]

// Consumer — completely unaware of multi-tenancy
class IngestionService {
  constructor(private readonly uniqueAuth: UniqueServiceAuth) {}

  async doWork() {
    const headers = await this.uniqueAuth.getHeaders(); // just works
  }
}
```

## Alternative: factories hold the cache instead of TenantContext

```typescript
// TenantContext stays lean — no service flat fields
interface TenantContext {
  readonly name: string;
  readonly config: TenantConfig;
  readonly logger: Logger;
  isScanning: boolean;
}

// Factory manages per-tenant cache internally
class UniqueTenantAuthFactory {
  private readonly cache = new Map<string, UniqueServiceAuth>();
  getForTenant(name: string): UniqueServiceAuth { ... }
}

// Proxy injects factory, looks up by tenant name
@Injectable()
class UniqueServiceAuthProxy extends UniqueServiceAuth {
  constructor(private readonly factory: UniqueTenantAuthFactory) { super(); }
  async getHeaders() {
    return this.factory.getForTenant(getCurrentTenant().name).getHeaders();
  }
}
```

## When to adopt

Consider this pattern when:
- Many downstream services need per-tenant auth and shouldn't know about `TenantContext`
- The number of per-tenant services grows beyond 5+
- We want downstream services to be testable with plain DI mocking (no ASL setup in tests)
