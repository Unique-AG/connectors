CREATE TABLE "search_cursors" (
	"id" varchar PRIMARY KEY NOT NULL,
	"payload" jsonb NOT NULL,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
ALTER TABLE "search_cursors" ADD CONSTRAINT "search_cursors_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
CREATE INDEX "search_cursors_created_at_index" ON "search_cursors" USING btree ("created_at");