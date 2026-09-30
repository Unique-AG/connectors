ALTER TABLE "a2a_executions" ADD COLUMN "workflow_task_id" text;--> statement-breakpoint
ALTER TABLE "a2a_executions" ADD COLUMN "recoveries" integer DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD COLUMN "client_message_id" text;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD COLUMN "heartbeat_at" timestamp with time zone;--> statement-breakpoint
CREATE UNIQUE INDEX "a2a_executions_one_active_per_chat_unique" ON "a2a_executions" USING btree ("company_id","chat_id") WHERE "a2a_executions"."state" in ('submitted', 'sending', 'working', 'input-required', 'auth-required');--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD CONSTRAINT "a2a_tasks_client_message_unique" UNIQUE("company_id","user_id","context_id","client_message_id");