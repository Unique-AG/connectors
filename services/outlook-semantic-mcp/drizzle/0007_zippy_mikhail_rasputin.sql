ALTER TABLE "directories" ALTER COLUMN "ignore_for_sync" SET DEFAULT false;--> statement-breakpoint
ALTER TABLE "directories" ALTER COLUMN "ignore_for_sync" SET NOT NULL;