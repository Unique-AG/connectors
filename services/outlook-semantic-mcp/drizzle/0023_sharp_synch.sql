ALTER TABLE "inbox_configuration" RENAME TO "inbox_configurations";--> statement-breakpoint
ALTER TABLE "inbox_configurations" DROP CONSTRAINT "inbox_configuration_user_profile_id_unique";--> statement-breakpoint
ALTER TABLE "inbox_configurations" DROP CONSTRAINT "inbox_configuration_user_profile_id_user_profiles_id_fk";
--> statement-breakpoint
ALTER TABLE "inbox_configurations" ADD CONSTRAINT "inbox_configurations_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "inbox_configurations" ADD CONSTRAINT "inbox_configurations_user_profile_id_unique" UNIQUE("user_profile_id");