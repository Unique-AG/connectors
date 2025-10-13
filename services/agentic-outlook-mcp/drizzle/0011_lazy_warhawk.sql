ALTER TYPE "public"."ingestion_status" ADD VALUE 'weighted' BEFORE 'chunked';--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "version" varchar;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "unique_body_text" text;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "unique_body_html" text;--> statement-breakpoint
ALTER TABLE "emails" DROP COLUMN "body_text_fingerprint";--> statement-breakpoint
ALTER TABLE "emails" DROP COLUMN "body_html_fingerprint";