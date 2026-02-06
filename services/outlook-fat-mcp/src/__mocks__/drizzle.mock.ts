import { vi } from 'vitest';

class InsertBuilder<T = unknown> {
  public values = vi.fn((_values: unknown) => this);
  public onConflictDoUpdate = vi.fn((_args: unknown) => this);
  public constructor(private readonly db: MockDrizzleDatabase) {}
  public async returning(_projection?: unknown): Promise<T[]> {
    return (this.db.__nextInsertReturningRows as T[]) ?? ([] as T[]);
  }
}

class SelectBuilder<T = unknown> {
  public from = vi.fn((_table: unknown) => this);
  public leftJoin = vi.fn((_other: unknown, _on: unknown) => this);
  public where = vi.fn(async (_cond: unknown): Promise<T[]> => {
    return (this.db.__nextSelectRows as T[]) ?? ([] as T[]);
  });

  public constructor(private readonly db: MockDrizzleDatabase) {}
}

class DeleteBuilder<T = unknown> {
  public constructor(private readonly db: MockDrizzleDatabase) {}
  public where = vi.fn((_cond: unknown) => this);
  public async returning(_projection?: unknown): Promise<T[]> {
    return (this.db.__nextDeleteReturningRows as T[]) ?? ([] as T[]);
  }
}

class UpdateBuilder {
  public set = vi.fn((_values: unknown) => this);
  public where = vi.fn(async (_cond: unknown): Promise<void> => {});
}

export class MockDrizzleDatabase {
  public insert = vi.fn((_table: unknown) => new InsertBuilder(this));
  public select = vi.fn((_projection?: unknown) => new SelectBuilder(this));
  public delete = vi.fn((_table: unknown) => new DeleteBuilder(this));
  public update = vi.fn((_table: unknown) => new UpdateBuilder());

  // Simple query helpers used by TokenProvider
  public query = {
    userProfiles: {
      findFirst: vi.fn(async (_args: unknown) => this.__nextQueryUserProfile ?? undefined),
    },
  };

  // Configuration knobs per test
  public __nextInsertReturningRows: unknown[] | undefined;
  public __nextSelectRows: unknown[] | undefined;
  public __nextDeleteReturningRows: unknown[] | undefined;
  public __nextQueryUserProfile: unknown | undefined;
}

export const createMockDrizzleDatabase = (): MockDrizzleDatabase => new MockDrizzleDatabase();
