import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { A2aController } from './a2a.controller.js';
import { A2aSdkService } from './a2a-sdk.service.js';

@Module({
  controllers: [A2aController],
  providers: [A2aSdkService, KongIdentityGuard],
  exports: [A2aSdkService],
})
export class A2aServerModule {}
