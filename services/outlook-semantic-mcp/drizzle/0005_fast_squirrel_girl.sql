ALTER TABLE "directories_sync" RENAME COLUMN "last_delta_sync_runed_at" TO "last_delta_sync_ran_at";--> statement-breakpoint
ALTER TABLE "directories_sync" RENAME COLUMN "last_directory_sync_runned_at" TO "last_directory_sync_ran_at";--> statement-breakpoint
ALTER TABLE "oauth_clients" DROP CONSTRAINT "oauth_clients_clientId_unique";--> statement-breakpoint
ALTER TABLE "oauth_sessions" DROP CONSTRAINT "oauth_sessions_sessionId_unique";--> statement-breakpoint
ALTER TABLE "directories_sync" DROP CONSTRAINT "directories_sync_userProfileId_unique";--> statement-breakpoint
ALTER TABLE "subscriptions" DROP CONSTRAINT "subscriptions_subscriptionId_unique";--> statement-breakpoint
ALTER TABLE "user_profiles" DROP CONSTRAINT "user_profiles_provider_providerUserId_unique";--> statement-breakpoint
ALTER TABLE "oauth_clients" ADD CONSTRAINT "oauth_clients_client_id_unique" UNIQUE("client_id");--> statement-breakpoint
ALTER TABLE "oauth_sessions" ADD CONSTRAINT "oauth_sessions_session_id_unique" UNIQUE("session_id");--> statement-breakpoint
ALTER TABLE "directories_sync" ADD CONSTRAINT "directories_sync_user_profile_id_unique" UNIQUE("user_profile_id");--> statement-breakpoint
ALTER TABLE "subscriptions" ADD CONSTRAINT "subscriptions_subscription_id_unique" UNIQUE("subscription_id");--> statement-breakpoint
ALTER TABLE "user_profiles" ADD CONSTRAINT "user_profiles_provider_provider_user_id_unique" UNIQUE("provider","provider_user_id");