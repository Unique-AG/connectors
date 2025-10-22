import { relations } from "drizzle-orm";
import { integer, jsonb, pgTable, varchar } from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { timestamps } from "../../timestamps.columns";
import { emails } from "./emails.table";

export const vectors = pgTable('vectors', {
  id: varchar().primaryKey().$default(() => typeid('vector').toString()),

  name: varchar().notNull(),
  dimension: integer().notNull(),
  embeddings: jsonb().$type<number[][]>().notNull(),

  // References
  emailId: varchar().references(() => emails.id, { onDelete: 'cascade', onUpdate: 'cascade'}),
  ...timestamps,
});

export const vectorsRelations = relations(vectors, ({ one }) => ({
  email: one(emails, {
    fields: [vectors.emailId],
    references: [emails.id],
  }),
}));

export type Vector = typeof vectors.$inferSelect;
export type VectorInput = typeof vectors.$inferInsert;