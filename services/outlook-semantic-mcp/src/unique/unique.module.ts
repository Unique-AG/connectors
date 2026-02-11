import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { FetchOrCreateOutlookEmailsRootScopeCommand } from './fetch-or-create-outlook-emails-root-scope.command';
import { UniqueService } from './unique.service';
import { UniqueFilesService } from './unique-files.service';
import { UniqueScopesService } from './unique-scopes.service';

@Module({
  imports: [DrizzleModule],
  providers: [
    UniqueService,
    FetchOrCreateOutlookEmailsRootScopeCommand,
    UniqueFilesService,
    UniqueScopesService,
  ],
  exports: [
    UniqueService,
    FetchOrCreateOutlookEmailsRootScopeCommand,
    UniqueFilesService,
    UniqueScopesService,
  ],
})
export class UniqueModule {}
