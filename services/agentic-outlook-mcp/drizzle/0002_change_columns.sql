ALTER TABLE "folders" ADD COLUMN "original_name" varchar;--> statement-breakpoint
ALTER TABLE "sync_jobs" DROP COLUMN "folder_subscription_id";