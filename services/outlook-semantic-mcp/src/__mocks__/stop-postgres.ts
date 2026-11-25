import type { StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import type { Pool } from 'pg';

/**
 * `pool.end()` resolves once every client is dropped from the pool, before their sockets close,
 * and a dropped client has no error listener. Stopping the container then terminates those
 * sessions and surfaces FATAL 57P01 as an unhandled error. Wait for every client's `remove`.
 */
export async function stopPostgres(
  pool: Pool | undefined,
  container: StartedPostgreSqlContainer | undefined,
): Promise<void> {
  if (pool) {
    const open = pool.totalCount;
    let removed = 0;
    const allRemoved = new Promise<void>((resolve) => {
      if (open === 0) {
        resolve();
      }
      pool.on('remove', () => {
        removed += 1;
        if (removed === open) {
          resolve();
        }
      });
    });
    await pool.end();
    await allRemoved;
  }
  await container?.stop();
}
