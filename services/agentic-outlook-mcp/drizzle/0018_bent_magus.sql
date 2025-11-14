ALTER TABLE "emails" ALTER COLUMN "ingestion_status" DROP DEFAULT;--> statement-breakpoint
ALTER TABLE "emails" ALTER COLUMN "ingestion_status" DROP NOT NULL;--> statement-breakpoint
ALTER TABLE "emails" ALTER COLUMN "ingestion_status" SET DATA TYPE text;--> statement-breakpoint
DROP TYPE "public"."ingestion_status";--> statement-breakpoint
CREATE TYPE "public"."ingestion_status" AS ENUM('pending', 'processed', 'densely-embedded', 'sparsely-embedded', 'completed', 'failed');--> statement-breakpoint
ALTER TABLE "emails" ALTER COLUMN "ingestion_status" SET DATA TYPE "public"."ingestion_status" USING "ingestion_status"::"public"."ingestion_status";