import { Module } from '@nestjs/common';
import { ClusterIdentityGuard } from '../auth/identity.guard.js';
import { InternalController } from './internal.controller.js';

@Module({ controllers: [InternalController], providers: [ClusterIdentityGuard] })
export class InternalModule {}
