ALTER TABLE "a2a_connections" ADD COLUMN "assistant_id" text;--> statement-breakpoint
ALTER TABLE "a2a_executions" ADD COLUMN "cancel_requested_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "a2a_executions" ADD COLUMN "finished_at" timestamp with time zone;--> statement-breakpoint
ALTER TABLE "a2a_connections" ADD CONSTRAINT "a2a_connections_company_assistant_unique" UNIQUE("company_id","assistant_id");