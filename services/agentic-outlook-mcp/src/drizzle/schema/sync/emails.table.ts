import { relations, sql } from 'drizzle-orm';
import {
  boolean,
  index,
  integer,
  jsonb,
  pgEnum,
  pgTable,
  text,
  timestamp,
  varchar,
} from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { userProfiles } from '../user-profiles.table';
import { folders } from './folders.table';

export const ingestionStatus = pgEnum('ingestion_status', [
  'pending',
  'ingested',
  'processed',
  'chunked',
  'embedded',
  'completed', // == indexed
  'failed',
]);

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

    sentAt: timestamp({ mode: "string" }),
    receivedAt: timestamp({ mode: "string" }),

    subject: text(),
    preview: text(),
    bodyText: text(),
    bodyTextFingerprint: text(),
    bodyHtml: text(),
    bodyHtmlFingerprint: text(),

    processedBody: text(),

    isRead: boolean().notNull().default(true),
    isDraft: boolean().notNull().default(false),
    sizeBytes: integer(),

    tags: text().array(),

    hasAttachments: boolean().notNull().default(false),
    attachments: jsonb()
      .$type<
        Array<{
          id: string | undefined | null;
          filename: string | undefined | null;
          mimeType: string | undefined | null;
          sizeBytes: number | undefined | null;
          isInline: boolean | undefined | null;
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

    // Ingestion Status
    ingestionStatus: ingestionStatus().notNull().default('pending'),
    ingestionLastError: text(),
    ingestionLastAttemptAt: timestamp({ mode: "string" }),
    ingestionCompletedAt: timestamp({ mode: "string" }),

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

export type EmailInput = typeof emails.$inferInsert;