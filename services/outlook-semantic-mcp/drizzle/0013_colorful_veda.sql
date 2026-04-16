ALTER TABLE "inbox_configuration" ALTER COLUMN "messages_from_microsoft" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "messages_queued_for_sync" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "messages_processed" SET NOT NULL;