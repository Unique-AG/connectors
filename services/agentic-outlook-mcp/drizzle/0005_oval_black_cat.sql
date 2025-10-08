ALTER TABLE "subscriptions" ALTER COLUMN "subscription_id" DROP NOT NULL;--> statement-breakpoint
ALTER TABLE "subscriptions" ALTER COLUMN "expires_at" DROP NOT NULL;