import { AesGcmEncryptionModule } from '@unique-ag/aes-gcm-encryption';
import { Module } from '@nestjs/common';

import { ResourceAuthorizationService } from '../auth/resource-authorization.service.js';
import { UniqueModule } from '../unique/unique.module.js';
import { PgTaskStore } from '../a2a-server/pg-task.store.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { CredentialVault } from '../credentials/credential-vault.js';
import { ConnectionRepository } from './connection.repository.js';
import { ContextRepository } from './context.repository.js';
import { DrizzleModule } from './drizzle.module.js';
import { ExecutionRepository } from './execution.repository.js';
import { PublicationRepository } from './publication.repository.js';

@Module({
  imports: [
    DrizzleModule,
    UniqueModule,
    AesGcmEncryptionModule.registerAsync({
      inject: [GATEWAY_CONFIG],
      useFactory: (config: GatewayConfig) => ({ key: config.encryptionKey }),
    }),
  ],
  providers: [
    ResourceAuthorizationService,
    CredentialVault,
    ConnectionRepository,
    ContextRepository,
    ExecutionRepository,
    PgTaskStore,
    PublicationRepository,
  ],
  exports: [
    ResourceAuthorizationService,
    CredentialVault,
    ConnectionRepository,
    ContextRepository,
    ExecutionRepository,
    PgTaskStore,
    PublicationRepository,
  ],
})
export class PersistenceModule {}
