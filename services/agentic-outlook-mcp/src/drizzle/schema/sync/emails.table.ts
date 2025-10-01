import { relations, sql } from 'drizzle-orm';
import {
  boolean,
  index,
  integer,
  jsonb,
  pgTable,
  text,
  timestamp,
  varchar,
} from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';
import { folders } from './folders.table';

export const emails = pgTable(
  'emails',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('email').toString()),
    messageId: varchar().notNull().unique(),
    conversationId: varchar(),
    internetMessageId: varchar(),
    webLink: varchar(),

    from: jsonb().$type<{ name: string | null; address: string } | null>(),
    sender: jsonb().$type<{ name: string | null; address: string } | null>(),
    replyTo: jsonb().$type<Array<{ name: string | null; address: string }> | null>(),
    to: jsonb()
      .$type<Array<{ name: string | null; address: string }>>()
      .notNull()
      .default(sql`'[]'::jsonb`),
    cc: jsonb()
      .$type<Array<{ name: string | null; address: string }>>()
      .notNull()
      .default(sql`'[]'::jsonb`),
    bcc: jsonb()
      .$type<Array<{ name: string | null; address: string }>>()
      .notNull()
      .default(sql`'[]'::jsonb`),

    sentAt: timestamp(),
    receivedAt: timestamp(),

    subject: text(),
    preview: text(),
    bodyText: text(),
    bodyHtml: text(),

    isRead: boolean().notNull().default(true),
    isDraft: boolean().notNull().default(false),
    sizeBytes: integer(),

    tags: text().array(),

    attachments: jsonb()
      .$type<
        Array<{
          id: string | null;
          filename: string | null;
          mimeType: string | null;
          sizeBytes: number | null;
          isInline: boolean | null;
          contentId: string | null;
        }>
      >()
      .notNull()
      .default(sql`'[]'::jsonb`),
    attachmentCount: integer().notNull().default(0),
    headers: jsonb().$type<Record<string, string> | null>(),

    // References
    userProfileId: varchar()
      .notNull()
      .references(() => userProfiles.id, { onDelete: 'cascade', onUpdate: 'cascade' }),
    folderId: varchar()
      .notNull()
      .references(() => folders.id, { onDelete: 'cascade', onUpdate: 'cascade' }),

    ...timestamps,
  },
  (table) => [
    index().on(table.messageId),
    index().on(table.conversationId),
    index().on(table.internetMessageId),
    index().on(table.isRead, table.isDraft),
  ],
);

export const emailRelations = relations(emails, ({ one }) => ({
  userProfile: one(userProfiles, {
    fields: [emails.userProfileId],
    references: [userProfiles.id],
  }),
  folder: one(folders, {
    fields: [emails.folderId],
    references: [folders.id],
  }),
}));