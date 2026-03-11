-- Add new enum values to inbox_sync_state
ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'fetching-emails';
ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'performing-file-diff';
ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'processing-file-diff-changes';
ALTER TYPE "public"."inbox_sync_state" ADD VALUE 'full-sync-finished';
--> statement-breakpoint

-- Update existing rows: rename idle -> full-sync-finished
UPDATE "inbox_configuration" SET "sync_state" = 'full-sync-finished' WHERE "sync_state" = 'idle';
--> statement-breakpoint

-- Rename column sync_state -> full_sync_state
ALTER TABLE "inbox_configuration" RENAME COLUMN "sync_state" TO "full_sync_state";
--> statement-breakpoint

-- Rename column sync_started_at -> last_full_sync_started_at
ALTER TABLE "inbox_configuration" RENAME COLUMN "sync_started_at" TO "last_full_sync_started_at";
--> statement-breakpoint

-- Add full_sync_version column (UUID, nullable)
ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_version" uuid;
