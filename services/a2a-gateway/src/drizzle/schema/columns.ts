import { customType, text, timestamp } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';

export type GatewayIdPrefix = 'pub' | 'conn' | 'ctx' | 'task' | 'art' | 'pnc' | 'exec' | 'rctx';

export const bytea = customType<{ data: Buffer; driverData: Buffer }>({
  dataType: () => 'bytea',
  toDriver: (value) => value,
  fromDriver: (value) => value,
});

export const timestamps = {
  createdAt: timestamp({ withTimezone: true }).defaultNow().notNull(),
  updatedAt: timestamp({ withTimezone: true }).defaultNow().notNull(),
};

export const typeId = (prefix: GatewayIdPrefix) =>
  text()
    .primaryKey()
    .$default(() => typeid(prefix).toString());
