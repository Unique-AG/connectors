import { existsSync } from 'node:fs';

// Nest's ConfigModule loads this file asynchronously, after the modules that read the features
// while they load (tool decorators, AppModule's imports). Load it first, with the same file choice
// and the same precedence: a variable already set keeps its value.
const envFile = process.env.NODE_ENV === 'test' ? '.env.test' : '.env';
if (existsSync(envFile)) {
  process.loadEnvFile(envFile);
}
