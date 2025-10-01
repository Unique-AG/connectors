ALTER TABLE "sync_jobs" DISABLE ROW LEVEL SECURITY;--> statement-breakpoint
DROP TABLE "sync_jobs" CASCADE;--> statement-breakpoint
--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "sync_activated_at" timestamp;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "sync_deactivated_at" timestamp;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "sync_last_synced_at" timestamp;--> statement-breakpoint
ALTER TABLE "folders" DROP COLUMN "sync_job_id";