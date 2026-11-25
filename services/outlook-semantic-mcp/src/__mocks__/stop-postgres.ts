import assert from 'node:assert';
import type { StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { Pool } from 'pg';

const openClients = new WeakMap<Pool, Set<unknown>>();

export function createPostgresPool(connectionString: string): Pool {
  const pool = new Pool({ connectionString });
  const open = new Set<unknown>();
  pool.on('connect', (client) => open.add(client));
  pool.on('remove', (client) => open.delete(client));
  openClients.set(pool, open);
  return pool;
}

// pool.end() resolves before its clients' sockets close; stopping the container first surfaces
// FATAL 57P01 on a client that no longer has an error listener.
export async function stopPostgres(
  pool: Pool | undefined,
  container: StartedPostgreSqlContainer | undefined,
): Promise<void> {
  if (pool) {
    const open = openClients.get(pool);
    assert.ok(open, 'stopPostgres needs a pool from createPostgresPool');
    const allClosed = new Promise<void>((resolve) => {
      const resolveWhenClosed = () => {
        if (open.size === 0) {
          resolve();
        }
      };
      pool.on('remove', resolveWhenClosed);
      resolveWhenClosed();
    });
    await pool.end();
    await allClosed;
  }
  await container?.stop();
}
