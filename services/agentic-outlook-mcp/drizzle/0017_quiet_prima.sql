ALTER TABLE "points" ADD COLUMN "qdrant_id" uuid DEFAULT gen_random_uuid() NOT NULL;--> statement-breakpoint
ALTER TABLE "points" ADD CONSTRAINT "points_qdrantId_unique" UNIQUE("qdrant_id");