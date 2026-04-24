ALTER TABLE "inbox_configurations" ADD COLUMN "deleting_inbox_started_at" timestamp;--> statement-breakpoint
ALTER TABLE "inbox_configurations" ADD COLUMN "deleting_heartbeat_at" timestamp;