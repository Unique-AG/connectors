ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_heartbeat_at" SET DEFAULT now();--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_heartbeat_at" SET NOT NULL;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "live_catch_up_heartbeat_at" SET DEFAULT now();--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "live_catch_up_heartbeat_at" SET NOT NULL;