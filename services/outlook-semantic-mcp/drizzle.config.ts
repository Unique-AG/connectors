import { defineConfig } from 'drizzle-kit';

export default defineConfig({
  out: './drizzle',
  schema: './src/db/schema/*',
  dialect: 'postgresql',
  dbCredentials: {
    // biome-ignore lint/style/noNonNullAssertion: It will fail if the database url is not set
    url: process.env.DATABASE_URL!,
  },
  casing: 'snake_case',
});
