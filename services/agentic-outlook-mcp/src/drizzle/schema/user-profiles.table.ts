import { relations } from 'drizzle-orm';
import { jsonb, pgTable, timestamp, unique, varchar } from 'drizzle-orm/pg-core';
import { createInsertSchema, createUpdateSchema } from 'drizzle-zod';
import { typeid } from 'typeid-js';
import * as z from 'zod';
import { camelizeKeys } from '../../utils/case-converter';
import { timestamps } from '../timestamps.columns';
import { authorizationCodes } from './auth/authorization-codes.table';
import { tokens } from './auth/tokens.table';
import { emails, folders } from './sync';

export const userProfiles = pgTable(
  'user_profiles',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('user_profile').toString()),
    provider: varchar().notNull(),
    providerUserId: varchar().notNull(),
    username: varchar().notNull(),
    email: varchar(),
    displayName: varchar(),
    avatarUrl: varchar(),
    raw: jsonb(),
    accessToken: varchar(),
    refreshToken: varchar(),
    syncActivatedAt: timestamp({ mode: 'string' }),
    syncDeactivatedAt: timestamp({ mode: 'string' }),
    syncLastSyncedAt: timestamp({ mode: 'string' }),
    ...timestamps,
  },
  (table) => [unique().on(table.provider, table.providerUserId)],
);

export const userProfileRelations = relations(userProfiles, ({ many }) => ({
  authorizationCodes: many(authorizationCodes),
  tokens: many(tokens),
  folders: many(folders),
  emails: many(emails),
}));

export type UserProfileInput = typeof userProfiles.$inferInsert;
export const userInsertSchema = createInsertSchema(userProfiles);
export const userInsertSchemaCamelized = z.unknown().transform(camelizeKeys).pipe(userInsertSchema);

export const userUpdateSchema = createUpdateSchema(userProfiles);
export const userUpdateSchemaCamelized = z.unknown().transform(camelizeKeys).pipe(userUpdateSchema);
export type UserUpdateZod = z.infer<typeof userUpdateSchema>;