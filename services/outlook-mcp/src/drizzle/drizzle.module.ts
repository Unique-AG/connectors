import { Module } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { drizzle, NodePgDatabase } from 'drizzle-orm/node-postgres';
import { Pool } from 'pg';
import { AppConfig, AppSettings } from '../app-settings.enum';
import * as schema from './schema';

export const DRIZZLE = Symbol('DRIZZLE');
export type DrizzleDatabase = NodePgDatabase<typeof schema>;

@Module({
  imports: [],
  providers: [
    {
      provide: DRIZZLE,
      useFactory: (configService: ConfigService<AppConfig, true>) => {
        const pool = new Pool({
          connectionString: configService.get(AppSettings.DATABASE_URL),
        });
        const db = drizzle({ client: pool, casing: 'snake_case', schema });
        return db;
      },
      inject: [ConfigService],
    },
  ],
  exports: [DRIZZLE],
})
export class DrizzleModule {}
