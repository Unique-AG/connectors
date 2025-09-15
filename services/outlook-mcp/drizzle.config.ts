import 'dotenv/config';
import { defineConfig } from 'drizzle-kit';
import { validateConfig } from './src/app-settings.enum';

const config = validateConfig(process.env);

export default defineConfig({
  out: './drizzle',
  schema: './src/drizzle/schema/*',
  dialect: 'postgresql',
  dbCredentials: {
    url: config.DATABASE_URL,
  },
  casing: 'snake_case',
});
