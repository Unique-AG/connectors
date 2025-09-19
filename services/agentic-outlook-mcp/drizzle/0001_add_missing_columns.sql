ALTER TABLE "sync_jobs" ADD COLUMN "folder_subscription_id" varchar;--> statement-breakpoint
ALTER TABLE "sync_jobs" ADD COLUMN "last_synced_at" timestamp;