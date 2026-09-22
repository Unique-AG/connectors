import { Module } from '@nestjs/common';
import { KongIdentityGuard } from '../auth/identity.guard.js';
import { ManagementController } from './management.controller.js';

@Module({ controllers: [ManagementController], providers: [KongIdentityGuard] })
export class ManagementModule {}
