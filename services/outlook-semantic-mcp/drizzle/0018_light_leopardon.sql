ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DATA TYPE text;--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DEFAULT 'ready'::text;--> statement-breakpoint
DROP TYPE "public"."inbox_sync_state";--> statement-breakpoint
CREATE TYPE "public"."inbox_sync_state" AS ENUM('ready', 'failed', 'running');--> statement-breakpoint
-- Safety net: convert any lingering 'fetching-emails' rows to 'ready' before the cast
UPDATE "inbox_configuration"
  SET "full_sync_state" = 'ready'
  WHERE "full_sync_state" = 'fetching-emails';--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DEFAULT 'ready'::"public"."inbox_sync_state";--> statement-breakpoint
ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DATA TYPE "public"."inbox_sync_state" USING "full_sync_state"::"public"."inbox_sync_state";--> statement-breakpoint
ALTER TABLE "inbox_configuration" DROP COLUMN "oldest_last_modified_date_time";