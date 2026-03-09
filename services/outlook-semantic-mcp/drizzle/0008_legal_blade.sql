CREATE TYPE "public"."inbox_sync_state" AS ENUM('idle', 'running', 'failed');--> statement-breakpoint
CREATE TABLE "inbox_configuration" (
	"id" varchar PRIMARY KEY NOT NULL,
	"user_profile_id" varchar NOT NULL,
	"filters" jsonb,
	"last_full_sync_run_at" timestamp,
	"sync_state" "inbox_sync_state" DEFAULT 'idle' NOT NULL,
	"sync_started_at" timestamp,
	"messages_from_microsoft" integer DEFAULT 0,
	"messages_queued_for_sync" integer DEFAULT 0,
	"messages_processed" integer DEFAULT 0,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "inbox_configuration_user_profile_id_unique" UNIQUE("user_profile_id")
);
--> statement-breakpoint
ALTER TABLE "inbox_configuration" ADD CONSTRAINT "inbox_configuration_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "subscriptions" DROP COLUMN "last_full_sync_run_at";--> statement-breakpoint
ALTER TABLE "subscriptions" DROP COLUMN "filters";