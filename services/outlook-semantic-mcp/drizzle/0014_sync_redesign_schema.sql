-- Replace inbox_sync_state enum: rename full-sync-finished->ready, drop performing-file-diff
-- and processing-file-diff-changes. Keep running, failed, fetching-emails.
CREATE TYPE "public"."inbox_sync_state_new" AS ENUM (
  'ready',
  'running',
  'failed',
  'fetching-emails'
);
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" DROP DEFAULT;
--> statement-breakpoint

ALTER TABLE "inbox_configuration"
  ALTER COLUMN "full_sync_state" TYPE "public"."inbox_sync_state_new"
  USING (
    CASE "full_sync_state"::text
      WHEN 'full-sync-finished' THEN 'ready'
      WHEN 'performing-file-diff' THEN 'ready'
      WHEN 'processing-file-diff-changes' THEN 'ready'
      ELSE "full_sync_state"::text
    END
  )::"public"."inbox_sync_state_new";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DEFAULT 'ready';
--> statement-breakpoint

DROP TYPE "public"."inbox_sync_state";
--> statement-breakpoint

ALTER TYPE "public"."inbox_sync_state_new" RENAME TO "inbox_sync_state";
--> statement-breakpoint

-- Create new live_catch_up_state enum and add column
CREATE TYPE "public"."live_catch_up_state" AS ENUM ('ready', 'running', 'failed');
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ADD COLUMN "live_catch_up_state" "public"."live_catch_up_state" DEFAULT 'ready' NOT NULL;
--> statement-breakpoint

-- Drop counter columns
ALTER TABLE "inbox_configuration" DROP COLUMN "messages_from_microsoft";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" DROP COLUMN "messages_queued_for_sync";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" DROP COLUMN "messages_processed";
--> statement-breakpoint

-- Add date watermark columns
ALTER TABLE "inbox_configuration" ADD COLUMN "newest_created_date_time" timestamp;
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ADD COLUMN "oldest_created_date_time" timestamp;
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ADD COLUMN "newest_last_modified_date_time" timestamp;
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ADD COLUMN "oldest_last_modified_date_time" timestamp;
