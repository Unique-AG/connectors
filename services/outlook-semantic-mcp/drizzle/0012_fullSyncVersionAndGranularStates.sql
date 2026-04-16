-- Replace inbox_sync_state enum: adds granular states, renames idle->full-sync-finished, drops idle.
-- Cannot use ALTER TYPE ADD VALUE inside a transaction (PostgreSQL restriction), so we
-- create a new type, migrate the column with a USING cast, drop the old type, then rename.
CREATE TYPE "public"."inbox_sync_state_new" AS ENUM (
  'full-sync-finished',
  'running',
  'failed',
  'fetching-emails',
  'performing-file-diff',
  'processing-file-diff-changes'
);
--> statement-breakpoint

-- Drop the default before changing the column type (PostgreSQL cannot auto-cast it)
ALTER TABLE "inbox_configuration" ALTER COLUMN "sync_state" DROP DEFAULT;
--> statement-breakpoint

ALTER TABLE "inbox_configuration"
  ALTER COLUMN "sync_state" TYPE "public"."inbox_sync_state_new"
  USING (
    CASE "sync_state"::text
      WHEN 'idle' THEN 'full-sync-finished'
      ELSE "sync_state"::text
    END
  )::"public"."inbox_sync_state_new";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ALTER COLUMN "sync_state" SET DEFAULT 'full-sync-finished';
--> statement-breakpoint

DROP TYPE "public"."inbox_sync_state";
--> statement-breakpoint

ALTER TYPE "public"."inbox_sync_state_new" RENAME TO "inbox_sync_state";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" RENAME COLUMN "sync_state" TO "full_sync_state";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" RENAME COLUMN "sync_started_at" TO "last_full_sync_started_at";
--> statement-breakpoint

ALTER TABLE "inbox_configuration" ADD COLUMN "full_sync_version" uuid;
