CREATE TYPE "public"."ingestion_status" AS ENUM('pending', 'ingested', 'processed', 'chunked', 'embedded', 'completed', 'failed');--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "ingestion_status" "ingestion_status" DEFAULT 'pending' NOT NULL;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "ingestion_attempts" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "ingestion_last_error" text;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "ingestion_last_attempt_at" timestamp;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "ingestion_completed_at" timestamp;