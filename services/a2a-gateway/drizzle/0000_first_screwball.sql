CREATE TABLE "a2a_artifacts" (
	"id" text PRIMARY KEY NOT NULL,
	"task_id" text NOT NULL,
	"company_id" text NOT NULL,
	"kind" text NOT NULL,
	"content_id" text,
	"artifact_snapshot" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_artifacts_kind" CHECK ("a2a_artifacts"."kind" in ('text', 'data', 'file'))
);
--> statement-breakpoint
CREATE TABLE "a2a_connections" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"name" text NOT NULL,
	"agent_card_url" text NOT NULL,
	"agent_card_snapshot" jsonb,
	"negotiated_capabilities" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"credential_type" text,
	"credential_ciphertext" "bytea",
	"version" integer DEFAULT 1 NOT NULL,
	"last_verified_at" timestamp with time zone,
	"last_error" text,
	"disabled_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_connections_company_id_unique" UNIQUE("company_id","id"),
	CONSTRAINT "a2a_connections_company_name_unique" UNIQUE("company_id","name"),
	CONSTRAINT "a2a_connections_version_positive" CHECK ("a2a_connections"."version" > 0)
);
--> statement-breakpoint
CREATE TABLE "a2a_contexts" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"user_id" text NOT NULL,
	"publication_id" text NOT NULL,
	"chat_id" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_contexts_company_id_unique" UNIQUE("company_id","id"),
	CONSTRAINT "a2a_contexts_company_chat_unique" UNIQUE("company_id","chat_id")
);
--> statement-breakpoint
CREATE TABLE "a2a_executions" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"user_id" text NOT NULL,
	"connection_id" text NOT NULL,
	"assistant_id" text NOT NULL,
	"chat_id" text NOT NULL,
	"user_message_id" text NOT NULL,
	"assistant_message_id" text NOT NULL,
	"remote_task_id" text,
	"state" text NOT NULL,
	"correlation" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"elicitation_id" text,
	"deadline_at" timestamp with time zone,
	"last_error" text,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_executions_company_user_message_unique" UNIQUE("company_id","user_message_id")
);
--> statement-breakpoint
CREATE TABLE "a2a_publications" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"assistant_id" text NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"card_overrides" jsonb DEFAULT '{}'::jsonb NOT NULL,
	"skills" jsonb DEFAULT '[]'::jsonb NOT NULL,
	"version" integer DEFAULT 1 NOT NULL,
	"created_by_user_id" text NOT NULL,
	"disabled_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_publications_company_id_unique" UNIQUE("company_id","id"),
	CONSTRAINT "a2a_publications_company_assistant_unique" UNIQUE("company_id","assistant_id"),
	CONSTRAINT "a2a_publications_version_positive" CHECK ("a2a_publications"."version" > 0)
);
--> statement-breakpoint
CREATE TABLE "a2a_push_notification_configs" (
	"id" text PRIMARY KEY NOT NULL,
	"task_id" text NOT NULL,
	"company_id" text NOT NULL,
	"url" text NOT NULL,
	"auth_ciphertext" "bytea",
	"failures" integer DEFAULT 0 NOT NULL,
	"disabled_at" timestamp with time zone,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_push_configs_task_url_unique" UNIQUE("task_id","url"),
	CONSTRAINT "a2a_push_configs_failures_nonnegative" CHECK ("a2a_push_notification_configs"."failures" >= 0)
);
--> statement-breakpoint
CREATE TABLE "a2a_remote_contexts" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"connection_id" text NOT NULL,
	"chat_id" text NOT NULL,
	"remote_context_id" text NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_remote_contexts_company_chat_unique" UNIQUE("company_id","chat_id"),
	CONSTRAINT "a2a_remote_contexts_connection_remote_unique" UNIQUE("company_id","connection_id","remote_context_id")
);
--> statement-breakpoint
CREATE TABLE "a2a_tasks" (
	"id" text PRIMARY KEY NOT NULL,
	"company_id" text NOT NULL,
	"user_id" text NOT NULL,
	"client_id" text NOT NULL,
	"context_id" text NOT NULL,
	"state" text NOT NULL,
	"user_message_id" text NOT NULL,
	"assistant_message_id" text,
	"elicitation_id" text,
	"task_snapshot" jsonb NOT NULL,
	"status_timestamp" timestamp with time zone DEFAULT now() NOT NULL,
	"expires_at" timestamp with time zone NOT NULL,
	"created_at" timestamp with time zone DEFAULT now() NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now() NOT NULL,
	CONSTRAINT "a2a_tasks_company_id_unique" UNIQUE("company_id","id"),
	CONSTRAINT "a2a_tasks_company_user_message_unique" UNIQUE("company_id","user_message_id")
);
--> statement-breakpoint
ALTER TABLE "a2a_artifacts" ADD CONSTRAINT "a2a_artifacts_company_task_fk" FOREIGN KEY ("company_id","task_id") REFERENCES "public"."a2a_tasks"("company_id","id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_contexts" ADD CONSTRAINT "a2a_contexts_company_publication_fk" FOREIGN KEY ("company_id","publication_id") REFERENCES "public"."a2a_publications"("company_id","id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_executions" ADD CONSTRAINT "a2a_executions_company_connection_fk" FOREIGN KEY ("company_id","connection_id") REFERENCES "public"."a2a_connections"("company_id","id") ON DELETE restrict ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_push_notification_configs" ADD CONSTRAINT "a2a_push_configs_company_task_fk" FOREIGN KEY ("company_id","task_id") REFERENCES "public"."a2a_tasks"("company_id","id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_remote_contexts" ADD CONSTRAINT "a2a_remote_contexts_company_connection_fk" FOREIGN KEY ("company_id","connection_id") REFERENCES "public"."a2a_connections"("company_id","id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD CONSTRAINT "a2a_tasks_company_context_fk" FOREIGN KEY ("company_id","context_id") REFERENCES "public"."a2a_contexts"("company_id","id") ON DELETE cascade ON UPDATE no action;--> statement-breakpoint
CREATE INDEX "a2a_artifacts_task_idx" ON "a2a_artifacts" USING btree ("company_id","task_id");--> statement-breakpoint
CREATE INDEX "a2a_connections_company_idx" ON "a2a_connections" USING btree ("company_id");--> statement-breakpoint
CREATE INDEX "a2a_contexts_owner_idx" ON "a2a_contexts" USING btree ("company_id","user_id");--> statement-breakpoint
CREATE INDEX "a2a_executions_recovery_idx" ON "a2a_executions" USING btree ("company_id","state","updated_at");--> statement-breakpoint
CREATE INDEX "a2a_executions_expiry_idx" ON "a2a_executions" USING btree ("expires_at");--> statement-breakpoint
CREATE INDEX "a2a_publications_company_enabled_idx" ON "a2a_publications" USING btree ("company_id","enabled");--> statement-breakpoint
CREATE INDEX "a2a_push_configs_company_task_idx" ON "a2a_push_notification_configs" USING btree ("company_id","task_id");--> statement-breakpoint
CREATE UNIQUE INDEX "a2a_tasks_one_active_per_context_unique" ON "a2a_tasks" USING btree ("context_id") WHERE "a2a_tasks"."state" not in ('3', '4', '5', '7');--> statement-breakpoint
CREATE INDEX "a2a_tasks_owner_status_idx" ON "a2a_tasks" USING btree ("company_id","user_id","status_timestamp","id");--> statement-breakpoint
CREATE INDEX "a2a_tasks_expiry_idx" ON "a2a_tasks" USING btree ("expires_at");