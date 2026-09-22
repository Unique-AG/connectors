import { Module } from '@nestjs/common';
import { UniqueInternalClient } from './unique-internal.client.js';

@Module({ providers: [UniqueInternalClient], exports: [UniqueInternalClient] })
export class UniqueModule {}
