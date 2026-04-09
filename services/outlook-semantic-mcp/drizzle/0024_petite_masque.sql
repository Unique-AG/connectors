ALTER TABLE "inbox_configurations" RENAME COLUMN "oldest_created_date_time" TO "oldest_received_email_date_time";--> statement-breakpoint
ALTER TABLE "inbox_configurations" RENAME COLUMN "newest_created_date_time" TO "newest_received_email_date_time";--> statement-breakpoint
ALTER TABLE "inbox_configurations" ALTER COLUMN "newest_last_modified_date_time" SET DEFAULT now();--> statement-breakpoint
UPDATE "inbox_configurations" SET "newest_last_modified_date_time" = now() WHERE "newest_last_modified_date_time" IS NULL;--> statement-breakpoint
ALTER TABLE "inbox_configurations" ALTER COLUMN "newest_last_modified_date_time" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configurations" DROP COLUMN "pending_live_message_ids";