import { relations } from "drizzle-orm";
import { integer, jsonb, pgEnum, pgTable, uuid, varchar } from "drizzle-orm/pg-core";
import { typeid } from "typeid-js";
import { timestamps } from "../../timestamps.columns";
import { emails } from "./emails.table";

export const pointType = pgEnum('point_type', ['chunk', 'summary', 'full']);

export const points = pgTable('points', {
  id: varchar().primaryKey().$default(() => typeid('vector').toString()),
  qdrantId: uuid().notNull().defaultRandom().unique(),
  pointType: pointType().notNull(),
  vector: jsonb().$type<number[]>().notNull(),
  index: integer().notNull(),
  
  // References
  emailId: varchar().references(() => emails.id, { onDelete: 'cascade', onUpdate: 'cascade'}),
  ...timestamps,
});

export const pointRelations = relations(points, ({ one }) => ({
  email: one(emails, {
    fields: [points.emailId],
    references: [emails.id],
  }),
}));

export type Point = typeof points.$inferSelect;
export type PointInput = typeof points.$inferInsert;