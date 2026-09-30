ALTER TABLE "a2a_executions" ADD COLUMN "bytes_in" bigint DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "a2a_executions" ADD COLUMN "bytes_out" bigint DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD COLUMN "bytes_in" bigint DEFAULT 0 NOT NULL;--> statement-breakpoint
ALTER TABLE "a2a_tasks" ADD COLUMN "bytes_out" bigint DEFAULT 0 NOT NULL;