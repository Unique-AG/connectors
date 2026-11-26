ALTER TABLE "user_profiles" ADD COLUMN "token_refresh_failed_at" timestamp;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "token_refresh_failure_count" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "token_refresh_failure_code" varchar;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "token_refresh_retry_at" timestamp;