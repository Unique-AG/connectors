import type { AMQPConfigNamespaced } from './amqp.config';
import type { AppConfigNamespaced } from './app.config';
import type { AuthConfigNamespaced } from './auth.config';
import type { DatabaseConfigNamespaced } from './database.config';
import { DelegatedAccessConfigNamespaced } from './delegated-access.config';
import type { EncryptionConfigNamespaced } from './encryption.config';
import { IngestionConfigNamespaced } from './ingestion.config';
import type { LogConfigNamespaced } from './log.config';
import type { MicrosoftConfigNamespaced } from './microsoft.config';
import type { UniqueConfigNamespaced } from './unique.config';

export * from './amqp.config';
export * from './app.config';
export * from './auth.config';
export * from './database.config';
export * from './delegated-access.config';
export * from './encryption.config';
export * from './ingestion.config';
export * from './log.config';
export * from './mcp-backend-type.config';
export * from './microsoft.config';
export * from './unique.config';

export type ConfigNamespaced = AMQPConfigNamespaced &
  AppConfigNamespaced &
  AuthConfigNamespaced &
  DatabaseConfigNamespaced &
  EncryptionConfigNamespaced &
  LogConfigNamespaced &
  MicrosoftConfigNamespaced &
  UniqueConfigNamespaced &
  DelegatedAccessConfigNamespaced &
  IngestionConfigNamespaced;
