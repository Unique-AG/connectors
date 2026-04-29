import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { caches, DRIZZLE, DrizzleDatabase } from '~/db';
import { CacheData, cacheData } from '~/db/schema/cache/cache.data';

interface SetWithData {
  currentValue: CacheData | null;
  create: (newValue: CacheData) => Promise<void>;
  update: (newValue: CacheData) => Promise<void>;
}
type SetWithDataFn<T> = (input: SetWithData) => Promise<T>;

@Injectable()
export class PersistentCacheService {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async set(key: string, item: CacheData) {
    await this.db
      .insert(caches)
      .values({
        key: this.getKey(key).toString(),
        data: item,
      })
      .onConflictDoUpdate({
        target: [caches.key],
        set: { data: item },
      });
  }

  public async setWith<T>(key: string, updateFn: SetWithDataFn<T>): Promise<T> {
    return await this.db.transaction(async (tx) => {
      const cacheKey = this.getKey(key).toString();
      const cacheKeyValue = await tx
        .select({ data: caches.data })
        .from(caches)
        .for('update')
        .where(eq(caches.key, cacheKey))
        .then((rows) => rows[0]?.data ?? null);

      const updateApi: SetWithData = {
        currentValue: cacheKeyValue,
        create: async (newValue: CacheData): Promise<void> => {
          const createdRows = await tx
            .insert(caches)
            .values({
              key: cacheKey,
              data: newValue,
            })
            .returning();

          assert.ok(createdRows.length > 0, `Update failed`);
        },
        update: async (newValue: CacheData): Promise<void> => {
          const rowsUpdated = await tx
            .insert(caches)
            .values({
              key: cacheKey,
              data: newValue,
            })
            .onConflictDoUpdate({
              target: [caches.key],
              set: { data: newValue },
            })
            .returning();

          assert.ok(rowsUpdated.length > 0, `Update failed`);
        },
      };

      return await updateFn(updateApi);
    });
  }

  public async get(key: string): Promise<CacheData | null> {
    const row = await this.db.query.caches.findFirst({
      where: eq(caches.key, this.getKey(key).toString()),
    });
    if (!row) {
      return null;
    }

    return cacheData.parse(row);
  }

  private getKey(key: string): string {
    return `cacheKey_${key}`;
  }
}
