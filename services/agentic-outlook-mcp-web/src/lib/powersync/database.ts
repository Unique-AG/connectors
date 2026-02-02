import { wrapPowerSyncWithDrizzle } from '@powersync/drizzle-driver';
import { PowerSyncDatabase } from '@powersync/web';
import { drizzleSchema, schema } from './schema';

export const powerSyncDb = new PowerSyncDatabase({
  database: {
    dbFilename: 'agentic-outlook-mcp.db',
  },
  schema,
});

export const db = wrapPowerSyncWithDrizzle(powerSyncDb, {
  schema: drizzleSchema,
});
