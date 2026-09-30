import { defineConfig } from 'drizzle-kit';

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  throw new Error('DATABASE_URL is required');
}

export default defineConfig({
  dialect: 'postgresql',
  schema: './src/drizzle/schema/*.table.ts',
  out: './drizzle',
  dbCredentials: { url: databaseUrl },
  casing: 'snake_case',
});
