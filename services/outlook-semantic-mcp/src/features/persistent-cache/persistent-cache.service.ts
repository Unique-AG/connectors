import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { fromString, parseTypeId, TypeID, typeid } from 'typeid-js';
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

  public async get<DataType extends CacheData['dataType']>(
    key: string,
    dataType: DataType,
  ): Promise<Extract<CacheData, { type: DataType }> | null> {
    const row = await this.db.query.caches.findFirst({
      where: eq(caches.key, this.getKey(key).toString()),
    });
    if (!row) {
      return null;
    }

    const rowParsed = cacheData.parse(row);
    assert.ok(
      rowParsed.dataType === dataType,
      `Row type: ${rowParsed.dataType} does not equal the expected row type: ${dataType} for key: ${key}`,
    );
    return rowParsed as unknown as Extract<CacheData, { type: DataType }> | null;
  }

  private getKey(key: string): TypeID<'cache'> {
    const tid = fromString(key, 'cache');
    const pid = parseTypeId(tid);
    return typeid(pid.prefix, pid.suffix);
  }
}
