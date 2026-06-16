CREATE TYPE "public"."user_profile_source" AS ENUM('oauth', 'shared-mailbox');--> statement-breakpoint
ALTER TABLE "directories_sync" ADD COLUMN "synchronized_by_user_profile_id" varchar;--> statement-breakpoint
ALTER TABLE "user_profiles" ADD COLUMN "source" "user_profile_source" DEFAULT 'oauth' NOT NULL;--> statement-breakpoint
ALTER TABLE "directories_sync" ADD CONSTRAINT "directories_sync_synchronized_by_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("synchronized_by_user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE set null ON UPDATE cascade;