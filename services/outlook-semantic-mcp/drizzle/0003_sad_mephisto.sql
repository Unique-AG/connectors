ALTER TABLE "subscriptions" ADD COLUMN "last_full_sync_run_at" timestamp;--> statement-breakpoint
ALTER TABLE "subscriptions" ADD COLUMN "filters" jsonb;