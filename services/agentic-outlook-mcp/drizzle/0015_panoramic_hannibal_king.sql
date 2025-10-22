CREATE TABLE "vectors" (
	"id" varchar PRIMARY KEY NOT NULL,
	"name" varchar NOT NULL,
	"dimension" integer NOT NULL,
	"embeddings" jsonb NOT NULL,
	"email_id" varchar,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "vectors" ADD CONSTRAINT "vectors_email_id_emails_id_fk" FOREIGN KEY ("email_id") REFERENCES "public"."emails"("id") ON DELETE cascade ON UPDATE cascade;