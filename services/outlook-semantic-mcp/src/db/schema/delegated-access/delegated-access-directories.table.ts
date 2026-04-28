import { relations } from 'drizzle-orm';
import { pgTable, text, unique, varchar } from 'drizzle-orm/pg-core';
import { typeid } from 'typeid-js';
import { timestamps } from '../../timestamps.columns';
import { delegatedAccessPipeline } from './delegated-access-pipeline.table';

export const delegatedAccessDirectories = pgTable(
  'delegated_access_directories',
  {
    id: varchar()
      .primaryKey()
      .$default(() => typeid('dad').toString()),
    pipelineId: varchar(`pipeline_id`)
      .notNull()
      .references(() => delegatedAccessPipeline.id, {
        onDelete: 'cascade',
        onUpdate: 'cascade',
      }),
    directoryId: text(`directory_id`).notNull(),

    ...timestamps,
  },
  (t) => [unique('unique_pipeline_directory').on(t.pipelineId, t.directoryId)],
);

export const delegatedAccessDirectoriesRelations = relations(
  delegatedAccessDirectories,
  ({ one }) => ({
    pipeline: one(delegatedAccessPipeline, {
      fields: [delegatedAccessDirectories.pipelineId],
      references: [delegatedAccessPipeline.id],
    }),
  }),
);

export type DelegatedAccessDirectory = typeof delegatedAccessDirectories.$inferSelect;
