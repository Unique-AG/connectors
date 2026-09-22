import { Inject, Module, type OnApplicationShutdown } from '@nestjs/common';
import { drizzle, type NodePgDatabase } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';

import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import * as schema from './schema/index.js';

export const POSTGRES_POOL = Symbol('POSTGRES_POOL');
export const DRIZZLE = Symbol('DRIZZLE');
export type GatewayDatabase = NodePgDatabase<typeof schema>;

class PostgresLifecycle implements OnApplicationShutdown {
  public constructor(@Inject(POSTGRES_POOL) private readonly pool: Pool) {}

  public async onApplicationShutdown(): Promise<void> {
    await this.pool.end();
  }
}

@Module({
  providers: [
    {
      provide: POSTGRES_POOL,
      inject: [GATEWAY_CONFIG],
      useFactory: (config: GatewayConfig) =>
        new Pool({
          connectionString: config.databaseUrl.toString(),
          max: config.workerConcurrency + 5,
        }),
    },
    {
      provide: DRIZZLE,
      inject: [POSTGRES_POOL],
      useFactory: (pool: Pool): GatewayDatabase =>
        drizzle({ client: pool, casing: 'snake_case', schema }),
    },
    PostgresLifecycle,
  ],
  exports: [DRIZZLE, POSTGRES_POOL],
})
export class DrizzleModule {}
