CREATE TYPE "public"."email_sync_status" AS ENUM('active', 'paused', 'stopped');--> statement-breakpoint
CREATE TABLE "email_sync_configs" (
	"id" varchar PRIMARY KEY NOT NULL,
	"user_profile_id" varchar NOT NULL,
	"status" "email_sync_status" DEFAULT 'active' NOT NULL,
	"sync_from_date" timestamp NOT NULL,
	"delta_token" text,
	"next_link" text,
	"last_sync_at" timestamp,
	"last_error" text,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "email_sync_configs_userProfileId_unique" UNIQUE("user_profile_id")
);
--> statement-breakpoint
CREATE TABLE "email_sync_messages" (
	"id" varchar PRIMARY KEY NOT NULL,
	"email_sync_config_id" varchar NOT NULL,
	"internet_message_id" varchar,
	"immutable_id" varchar,
	"content_hash" varchar,
	"subject" text,
	"sender_email" varchar,
	"sender_name" varchar,
	"recipients" jsonb,
	"received_at" timestamp,
	"sent_at" timestamp,
	"byte_size" integer,
	"has_attachments" boolean DEFAULT false,
	"unique_content_id" varchar,
	"ingested_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "email_sync_configs" ADD CONSTRAINT "email_sync_configs_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "email_sync_messages" ADD CONSTRAINT "email_sync_messages_email_sync_config_id_email_sync_configs_id_fk" FOREIGN KEY ("email_sync_config_id") REFERENCES "public"."email_sync_configs"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
CREATE INDEX "email_sync_configs_user_profile_id_idx" ON "email_sync_configs" USING btree ("user_profile_id");--> statement-breakpoint
CREATE INDEX "email_sync_messages_config_id_idx" ON "email_sync_messages" USING btree ("email_sync_config_id");--> statement-breakpoint
CREATE INDEX "email_sync_messages_internet_message_id_idx" ON "email_sync_messages" USING btree ("internet_message_id");--> statement-breakpoint
CREATE INDEX "email_sync_messages_immutable_id_idx" ON "email_sync_messages" USING btree ("immutable_id");--> statement-breakpoint
CREATE INDEX "email_sync_messages_content_hash_idx" ON "email_sync_messages" USING btree ("content_hash");