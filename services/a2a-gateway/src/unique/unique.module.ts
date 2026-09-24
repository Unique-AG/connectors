import { Module } from '@nestjs/common';
import { AuthorizationService } from '../auth/authorization.service.js';
import { UniqueInternalClient } from './unique-internal.client.js';

@Module({
  providers: [UniqueInternalClient, AuthorizationService],
  exports: [UniqueInternalClient, AuthorizationService],
})
export class UniqueModule {}
