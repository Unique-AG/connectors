import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { UniqueService } from './unique.service';
import { UniqueApiClient } from './unique-api.client';
import { UniqueContentService } from './unique-content.service';
import { UniqueScopeService } from './unique-scope.service';
import { UniqueUserService } from './unique-user.service';

@Module({
  imports: [DrizzleModule],
  providers: [
    UniqueApiClient,
    UniqueUserService,
    UniqueScopeService,
    UniqueContentService,
    UniqueService,
  ],
  exports: [UniqueService, UniqueContentService, UniqueUserService, UniqueScopeService],
})
export class UniqueModule {}
