import { Inject, Injectable } from '@nestjs/common';
import { type HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import type { Pool } from 'pg';
import { POSTGRES_POOL } from '../drizzle/drizzle.module.js';

@Injectable()
export class DatabaseHealthIndicator {
  public constructor(
    @Inject(POSTGRES_POOL) private readonly pool: Pool,
    private readonly indicators: HealthIndicatorService,
  ) {}

  public async check(): Promise<HealthIndicatorResult> {
    const indicator = this.indicators.check('database');
    try {
      await this.pool.query('SELECT 1');
      return indicator.up();
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
