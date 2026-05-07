ALTER TABLE "delegated_access_pipelines" RENAME TO "delegated_access_accounts";--> statement-breakpoint
ALTER TABLE "delegated_access_directories" RENAME COLUMN "pipeline_id" TO "accounts_id";--> statement-breakpoint
ALTER TABLE "delegated_access_directories" DROP CONSTRAINT "unique_pipeline_directory";--> statement-breakpoint
ALTER TABLE "delegated_access_directories" DROP CONSTRAINT "delegated_access_directories_pipeline_id_delegated_access_pipelines_id_fk";
--> statement-breakpoint
ALTER TABLE "delegated_access_accounts" DROP CONSTRAINT "delegated_access_pipelines_delegate_user_id_user_profiles_id_fk";
--> statement-breakpoint
ALTER TABLE "delegated_access_accounts" DROP CONSTRAINT "delegated_access_pipelines_owner_user_id_user_profiles_id_fk";
--> statement-breakpoint
ALTER TABLE "delegated_access_directories" ADD CONSTRAINT "delegated_access_directories_accounts_id_delegated_access_accounts_id_fk" FOREIGN KEY ("accounts_id") REFERENCES "public"."delegated_access_accounts"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "delegated_access_accounts" ADD CONSTRAINT "delegated_access_accounts_delegate_user_id_user_profiles_id_fk" FOREIGN KEY ("delegate_user_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "delegated_access_accounts" ADD CONSTRAINT "delegated_access_accounts_owner_user_id_user_profiles_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "delegated_access_directories" ADD CONSTRAINT "unique_accounts_directory" UNIQUE("accounts_id","directory_id");