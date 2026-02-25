import { Module } from '@nestjs/common';
import { drizzle, NodePgDatabase } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import { type DatabaseConfig, databaseConfig } from '~/config';
import * as schema from './schema';

export const DRIZZLE = Symbol('DRIZZLE');
export type DrizzleDatabase = NodePgDatabase<typeof schema>;

@Module({
  imports: [],
  providers: [
    {
      provide: DRIZZLE,
      inject: [databaseConfig.KEY],
      useFactory: (config: DatabaseConfig): DrizzleDatabase => {
        const pool = new Pool({
          connectionString: config.url.value.toString(),
        });

        return drizzle({ client: pool, casing: 'snake_case', schema });
      },
    },
  ],
  exports: [DRIZZLE],
})
export class DrizzleModule {}
