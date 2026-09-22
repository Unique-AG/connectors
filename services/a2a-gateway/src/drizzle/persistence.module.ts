import { AesGcmEncryptionModule } from '@unique-ag/aes-gcm-encryption';
import { Module } from '@nestjs/common';

import { PgTaskStore } from '../a2a-server/pg-task.store.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { CredentialVault } from '../credentials/credential-vault.js';
import { DrizzleModule } from './drizzle.module.js';
import {
  ConnectionRepository,
  ExecutionRepository,
  PublicationRepository,
} from './gateway.repository.js';

@Module({
  imports: [
    DrizzleModule,
    AesGcmEncryptionModule.registerAsync({
      inject: [GATEWAY_CONFIG],
      useFactory: (config: GatewayConfig) => ({ key: config.encryptionKey }),
    }),
  ],
  providers: [
    CredentialVault,
    ConnectionRepository,
    ExecutionRepository,
    PgTaskStore,
    PublicationRepository,
  ],
  exports: [
    CredentialVault,
    ConnectionRepository,
    ExecutionRepository,
    PgTaskStore,
    PublicationRepository,
  ],
})
export class PersistenceModule {}
