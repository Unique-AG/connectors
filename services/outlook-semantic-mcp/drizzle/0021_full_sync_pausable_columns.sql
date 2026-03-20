ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'paused';--> statement-breakpoint
ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'waiting-for-ingestion';--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_batch_index" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_expected_total" integer;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_skipped" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_scheduled_for_ingestion" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_failed_to_upload_for_ingestion" integer DEFAULT 0 NOT NULL;