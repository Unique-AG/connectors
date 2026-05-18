CREATE TYPE "public"."user_profile_source" AS ENUM('oauth', 'shared-mailbox');--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "source" "user_profile_source" NOT NULL DEFAULT 'oauth';
