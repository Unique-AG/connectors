CREATE TYPE "public"."subscription_for_type" AS ENUM('folder');--> statement-breakpoint
CREATE TABLE "subscriptions" (
	"id" varchar PRIMARY KEY NOT NULL,
	"subscription_id" varchar NOT NULL,
	"resource" varchar NOT NULL,
	"expires_at" timestamp NOT NULL,
	"for_id" varchar NOT NULL,
	"for_type" "subscription_for_type" NOT NULL,
	"user_profile_id" varchar NOT NULL,
	"created_at" timestamp DEFAULT now() NOT NULL,
	"updated_at" timestamp DEFAULT now() NOT NULL,
	CONSTRAINT "subscriptions_subscriptionId_unique" UNIQUE("subscription_id")
);
--> statement-breakpoint
ALTER TABLE "folders" ADD COLUMN "subscription_type" varchar DEFAULT 'folder';--> statement-breakpoint
ALTER TABLE "subscriptions" ADD CONSTRAINT "subscriptions_user_profile_id_user_profiles_id_fk" FOREIGN KEY ("user_profile_id") REFERENCES "public"."user_profiles"("id") ON DELETE cascade ON UPDATE cascade;--> statement-breakpoint
ALTER TABLE "folders" DROP COLUMN "subscription_id";