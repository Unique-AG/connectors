CREATE TABLE "caches" (
	"key" varchar PRIMARY KEY NOT NULL,
	"filters" jsonb NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL
);
--> statement-breakpoint
CREATE TABLE "delegated_access_directories" (
	"id" varchar PRIMARY KEY NOT NULL,
	"pipeline_id" varchar NOT NULL,
	"directory_id" text NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "unique_pipeline_directory" UNIQUE("pipeline_id","directory_id")
);
--> statement-breakpoint
CREATE TABLE "delegated_access_pipelines" (
	"id" varchar PRIMARY KEY NOT NULL,
	"delegate_user_id" varchar NOT NULL,
	"owner_user_id" varchar NOT NULL,
	"last_discovered_at" timestamp,
	"last_verified_at" timestamp,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "unique_delegate_owner_pair" UNIQUE("delegate_user_id","owner_user_id")
);
--> statement-breakpoint
ALTER TABLE "delegated_access_directories" ADD CONSTRAINT "delegated_access_directories_pipeline_id_delegated_access_pipelines_id_fk" FOREIGN KEY ("pipeline_id") REFERENCES "public"."delegated_access_pipelines"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "delegated_access_pipelines" ADD CONSTRAINT "delegated_access_pipelines_delegate_user_id_user_profiles_id_fk" FOREIGN KEY ("delegate_user_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "delegated_access_pipelines" ADD CONSTRAINT "delegated_access_pipelines_owner_user_id_user_profiles_id_fk" FOREIGN KEY ("owner_user_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;