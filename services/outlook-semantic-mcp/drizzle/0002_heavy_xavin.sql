ALTER TABLE "subscriptions" ALTER COLUMN "internal_type" SET DATA TYPE text;--> statement-breakpoint
DROP TYPE "public"."subscription_internal_type";--> statement-breakpoint
CREATE TYPE "public"."subscription_internal_type" AS ENUM('mail_monitoring');--> statement-breakpoint
ALTER TABLE "subscriptions" ALTER COLUMN "internal_type" SET DATA TYPE "public"."subscription_internal_type" USING "internal_type"::"public"."subscription_internal_type";