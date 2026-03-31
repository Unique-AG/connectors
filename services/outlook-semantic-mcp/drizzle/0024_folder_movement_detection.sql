ALTER TABLE "directories_sync" ADD COLUMN "folder_movement_sync_state" varchar;--> statement-breakpoint
ALTER TABLE "directories_sync" ADD COLUMN "folder_movement_sync_heartbeat_at" timestamp;--> statement-breakpoint
ALTER TABLE "directories" ADD COLUMN "parent_change_detected_at" timestamp;--> statement-breakpoint
ALTER TABLE "directories" ADD COLUMN "directory_movement_resync_cursor" varchar;