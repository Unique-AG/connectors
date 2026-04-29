import { relations } from 'drizzle-orm';
import { pgTable, text, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { delegatedAccessPipelines } from './delegated-access-pipelines.table';

export const delegatedAccessDirectories = pgTable(
  'delegated_access_directories',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('dad').toString()),
    pipelineId: varchar(`pipeline_id`)
      .notNull()
      .references(() => delegatedAccessPipelines.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    // We do not make a foreign key out of this directory because the delegated access sync and the emails / directories sync
    // process should be decoupled and if we discover a new directory in a user inbox during delegate access sync we should be
    // able to add that directory id to our search.
    directoryId: text(`directory_id`).notNull(),

    ...timestamps,
  },
  (t) => [unique('unique_pipeline_directory').on(t.pipelineId, t.directoryId)],
);

export const delegatedAccessDirectoriesRelations = relations(
  delegatedAccessDirectories,
  ({ one }) => ({
    pipeline: one(delegatedAccessPipelines, {
      fields: [delegatedAccessDirectories.pipelineId],
      references: [delegatedAccessPipelines.id],
    }),
  }),
);

export type DelegatedAccessDirectory = typeof delegatedAccessDirectories.$inferSelect;
