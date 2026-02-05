import { relations } from 'drizzle-orm';
import { boolean, index, integer, jsonb, pgTable, timestamp, text, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { emailSyncConfigs } from './email-sync-configs.table';

export const emailSyncMessages = pgTable(
  'email_sync_messages',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('email_msg').toString()),
    emailSyncConfigId: varchar()
      .notNull()
      .references(() => emailSyncConfigs.id, { onDelete: 'cascade', onUpdate: 'cascade' }),

    // Multi-ID tracking for deduplication
    internetMessageId: varchar(),
    immutableId: varchar(),
    contentHash: varchar(),

    // Email metadata
    subject: text(),
    senderEmail: varchar(),
    senderName: varchar(),
    recipients: jsonb().$type<string[]>(),
    receivedAt: timestamp(),
    sentAt: timestamp(),
    byteSize: integer(),
    hasAttachments: boolean().default(false),

    // Ingestion tracking
    uniqueContentId: varchar(),
    ingestedAt: timestamp(),

    ...timestamps,
  },
  (t) => [
    index('email_sync_messages_config_id_idx').on(t.emailSyncConfigId),
    index('email_sync_messages_internet_message_id_idx').on(t.internetMessageId),
    index('email_sync_messages_immutable_id_idx').on(t.immutableId),
    index('email_sync_messages_content_hash_idx').on(t.contentHash),
  ],
);

export const emailSyncMessageRelations = relations(emailSyncMessages, ({ one }) => ({
  emailSyncConfig: one(emailSyncConfigs, {
    fields: [emailSyncMessages.emailSyncConfigId],
    references: [emailSyncConfigs.id],
  }),
}));

export type EmailSyncMessage = typeof emailSyncMessages.$inferSelect;
export type NewEmailSyncMessage = typeof emailSyncMessages.$inferInsert;
