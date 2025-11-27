ALTER TABLE "emails" RENAME COLUMN "processed_subject" TO "translated_body";--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "translated_subject" text;