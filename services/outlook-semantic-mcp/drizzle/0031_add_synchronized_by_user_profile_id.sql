ALTER TABLE "directories_sync" ADD COLUMN "synchronized_by_user_profile_id" varchar REFERENCES "user_profiles"("id") ON DELETE set null ON UPDATE cascade;
