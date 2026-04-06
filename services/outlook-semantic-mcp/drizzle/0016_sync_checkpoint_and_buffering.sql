ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_next_link" text;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "pending_live_message_ids" text[] DEFAULT '{}' NOT NULL;