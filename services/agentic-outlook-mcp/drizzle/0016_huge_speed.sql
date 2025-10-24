CREATE TYPE "public"."point_type" AS ENUM('chunk', 'summary', 'full');--> statement-breakpoint
ALTER TABLE "vectors" RENAME TO "points";--> statement-breakpoint
ALTER TABLE "points" RENAME COLUMN "embeddings" TO "vector";--> statement-breakpoint
ALTER TABLE "points" DROP CONSTRAINT "vectors_email_id_emails_id_fk";
--> statement-breakpoint
ALTER TABLE "points" ADD COLUMN "point_type" "point_type" NOT NULL;--> statement-breakpoint
ALTER TABLE "points" ADD COLUMN "index" integer NOT NULL;--> statement-breakpoint
ALTER TABLE "points" ADD CONSTRAINT "points_email_id_emails_id_fk" FOREIGN KEY ("email_id") REFERENCES "public"."emails"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "points" DROP COLUMN "name";--> statement-breakpoint
ALTER TABLE "points" DROP COLUMN "dimension";