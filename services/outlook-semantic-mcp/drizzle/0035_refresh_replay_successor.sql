ALTER TABLE "tokens" ADD COLUMN "replayed_at" timestamp;--> statement-breakpoint
ALTER TABLE "tokens" ADD COLUMN "successor" text;