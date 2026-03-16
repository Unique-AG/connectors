-- Remove unused 'running' value from inbox_sync_state enum.
-- The full sync flow only uses: ready, fetching-emails, failed.
CREATE TYPE "public"."inbox_sync_state_new" AS ENUM (
  'ready',
  'failed',
  'fetching-emails'
);
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" DROP DEFAULT;
--> statement-breakpoint

-- Safety net: convert any lingering 'running' rows to 'ready'
UPDATE "inbox_configuration"
  SET "full_sync_state" = 'ready'
  WHERE "full_sync_state"::text = 'running';
--> statement-breakpoint

ALTER TABLE "inbox_configuration"
  ALTER COLUMN "full_sync_state" TYPE "public"."inbox_sync_state_new"
  USING ("full_sync_state"::text)::"public"."inbox_sync_state_new";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ALTER COLUMN "full_sync_state" SET DEFAULT 'ready';
--> statement-breakpoint

DROP TYPE "public"."inbox_sync_state";
--> statement-breakpoint

ALTER TYPE "public"."inbox_sync_state_new" RENAME TO "inbox_sync_state";
