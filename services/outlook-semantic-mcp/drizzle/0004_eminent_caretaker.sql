CREATE TYPE "public"."directory_internal_type" AS ENUM('Archive', 'Deleted Items', 'Drafts', 'Inbox', 'Junk Email', 'Outbox', 'Sent Items', 'Conversation History', 'Recoverable Items Deletions', 'Clutter', 'User Defined Directory');--> statement-breakpoint
CREATE TABLE "directories_sync" (
	"id" varchar PRIMARY KEY NOT NULL,
	"delta_link" varchar,
	"last_delta_sync_runed_at" timestamp,
	"last_delta_change_detected_at" timestamp,
	"last_directory_sync_runned_at" timestamp,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "directories_sync_userProfileId_unique" UNIQUE("user_profile_id")
);
--> statement-breakpoint
CREATE TABLE "directories" (
	"id" varchar PRIMARY KEY NOT NULL,
	"internal_type" "directory_internal_type" NOT NULL,
	"provider_directory_id" varchar NOT NULL,
	"display_name" varchar NOT NULL,
	"parent_id" varchar,
	"ignore_for_sync" boolean,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "single_directory_per_user_profile" UNIQUE("user_profile_id","provider_directory_id")
);
--> statement-breakpoint
ALTER TABLE "directories_sync" ADD CONSTRAINT "directories_sync_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "directories" ADD CONSTRAINT "directories_parent_id_directories_id_fk" FOREIGN KEY ("parent_id") REFERENCES "public"."directories"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "directories" ADD CONSTRAINT "directories_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;