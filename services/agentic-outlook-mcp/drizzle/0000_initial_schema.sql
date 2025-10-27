CREATE TYPE "public"."token_type" AS ENUM('ACCESS', 'REFRESH');--> statement-breakpoint
CREATE TABLE "authorization_codes" (
	"id" varchar PRIMARY KEY NOT NULL,
	"code" varchar NOT NULL,
	"user_id" varchar NOT NULL,
	"client_id" varchar NOT NULL,
	"redirect_uri" varchar NOT NULL,
	"code_challenge" varchar NOT NULL,
	"code_challenge_method" varchar NOT NULL,
	"resource" varchar,
	"scope" varchar,
	"expires_at" timestamp NOT NULL,
	"used_at" timestamp,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "authorization_codes_code_unique" UNIQUE("code")
);
--> statement-breakpoint
CREATE TABLE "oauth_clients" (
	"id" varchar PRIMARY KEY NOT NULL,
	"client_id" varchar NOT NULL,
	"client_secret" varchar,
	"client_name" varchar NOT NULL,
	"client_description" varchar,
	"logo_uri" varchar,
	"client_uri" varchar,
	"developer_name" varchar,
	"developer_email" varchar,
	"redirect_uris" varchar[] NOT NULL,
	"grant_types" varchar[] NOT NULL,
	"response_types" varchar[] NOT NULL,
	"token_endpoint_auth_method" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "oauth_clients_clientId_unique" UNIQUE("client_id")
);
--> statement-breakpoint
CREATE TABLE "oauth_sessions" (
	"id" varchar PRIMARY KEY NOT NULL,
	"session_id" varchar NOT NULL,
	"state" varchar NOT NULL,
	"client_id" varchar,
	"redirect_uri" varchar,
	"code_challenge" varchar,
	"code_challenge_method" varchar,
	"oauth_state" varchar,
	"scope" varchar,
	"resource" varchar,
	"expires_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "oauth_sessions_sessionId_unique" UNIQUE("session_id")
);
--> statement-breakpoint
CREATE TABLE "tokens" (
	"id" varchar PRIMARY KEY NOT NULL,
	"token" varchar NOT NULL,
	"type" "token_type" NOT NULL,
	"expires_at" timestamp NOT NULL,
	"user_id" varchar NOT NULL,
	"client_id" varchar NOT NULL,
	"scope" varchar NOT NULL,
	"resource" varchar NOT NULL,
	"family_id" varchar,
	"generation" integer,
	"used_at" timestamp,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "tokens_token_unique" UNIQUE("token")
);
--> statement-breakpoint
CREATE TABLE "user_profiles" (
	"id" varchar PRIMARY KEY NOT NULL,
	"provider" varchar NOT NULL,
	"provider_user_id" varchar NOT NULL,
	"username" varchar NOT NULL,
	"email" varchar,
	"display_name" varchar,
	"avatar_url" varchar,
	"raw" jsonb,
	"access_token" varchar,
	"refresh_token" varchar,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "user_profiles_provider_providerUserId_unique" UNIQUE("provider","provider_user_id")
);
--> statement-breakpoint
CREATE TABLE "emails" (
	"id" varchar PRIMARY KEY NOT NULL,
	"message_id" varchar NOT NULL,
	"conversation_id" varchar,
	"internet_message_id" varchar,
	"web_link" varchar,
	"from" jsonb,
	"sender" jsonb,
	"reply_to" jsonb,
	"to" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"cc" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"bcc" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"sent_at" timestamp,
	"received_at" timestamp,
	"subject" text,
	"preview" text,
	"body_text" text,
	"body_html" text,
	"is_read" boolean DEFAULT true NOT NULL,
	"is_draft" boolean DEFAULT false NOT NULL,
	"size_bytes" integer,
	"tags" text[],
	"attachments" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"attachment_count" integer DEFAULT 0 NOT NULL,
	"headers" jsonb,
	"user_profile_id" varchar NOT NULL,
	"folder_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "emails_messageId_unique" UNIQUE("message_id")
);
--> statement-breakpoint
CREATE TABLE "folders" (
	"id" varchar PRIMARY KEY NOT NULL,
	"name" varchar NOT NULL,
	"folder_id" varchar NOT NULL,
	"parent_folder_id" varchar,
	"child_folder_count" integer DEFAULT 0 NOT NULL,
	"subscription_id" varchar,
	"sync_token" varchar,
	"activated_at" timestamp,
	"deactivated_at" timestamp,
	"last_synced_at" timestamp,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	"sync_job_id" varchar NOT NULL,
	CONSTRAINT "folders_folderId_unique" UNIQUE("folder_id")
);
--> statement-breakpoint
CREATE TABLE "sync_jobs" (
	"id" varchar PRIMARY KEY NOT NULL,
	"user_profile_id" varchar NOT NULL,
	"deactivated_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "authorization_codes" ADD CONSTRAINT "authorization_codes_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "tokens" ADD CONSTRAINT "tokens_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "emails" ADD CONSTRAINT "emails_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "emails" ADD CONSTRAINT "emails_folder_id_folders_id_fk" FOREIGN KEY ("folder_id") REFERENCES "public"."folders"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "folders" ADD CONSTRAINT "folders_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "folders" ADD CONSTRAINT "folders_sync_job_id_sync_jobs_id_fk" FOREIGN KEY ("sync_job_id") REFERENCES "public"."sync_jobs"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "sync_jobs" ADD CONSTRAINT "sync_jobs_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
CREATE INDEX "tokens_family_id_index" ON "tokens" USING btree ("family_id");--> statement-breakpoint
CREATE INDEX "tokens_expires_at_index" ON "tokens" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "tokens_user_profile_id_index" ON "tokens" USING btree ("user_profile_id");--> statement-breakpoint
CREATE INDEX "emails_message_id_index" ON "emails" USING btree ("message_id");--> statement-breakpoint
CREATE INDEX "emails_conversation_id_index" ON "emails" USING btree ("conversation_id");--> statement-breakpoint
CREATE INDEX "emails_internet_message_id_index" ON "emails" USING btree ("internet_message_id");--> statement-breakpoint
CREATE INDEX "emails_is_read_is_draft_index" ON "emails" USING btree ("is_read","is_draft");