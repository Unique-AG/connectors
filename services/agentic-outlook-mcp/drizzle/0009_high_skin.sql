ALTER TABLE "emails" ADD COLUMN "body_text_fingerprint" text;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "body_html_fingerprint" text;--> statement-breakpoint
ALTER TABLE "emails" ADD COLUMN "processed_body" text;