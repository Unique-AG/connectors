import { Module } from '@nestjs/common';
import { PersistenceModule } from '../drizzle/persistence.module.js';
import { UniqueModule } from '../unique/unique.module.js';
import { ConnectionService } from './connection.service.js';
import { CredentialProviderService } from './credential-provider.service.js';
import { EgressService } from './egress.service.js';

@Module({
  imports: [PersistenceModule, UniqueModule],
  providers: [ConnectionService, CredentialProviderService, EgressService],
  exports: [ConnectionService, CredentialProviderService],
})
export class CredentialsModule {}
