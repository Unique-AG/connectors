import { Module } from "@nestjs/common";
import { DrizzleModule } from "../drizzle/drizzle.module";
import { UniqueService } from "./unique.service";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "./unique-scopes/fetch-or-create-outlook-emails-root-scope.command";
import { UniqueScopesService } from "./unique-scopes/unique-scopes.service";

@Module({
  imports: [DrizzleModule],
  providers: [
    UniqueService,
    UniqueScopesService,
    FetchOrCreateOutlookEmailsRootScopeCommand,
  ],
  exports: [
    UniqueService,
    UniqueScopesService,
    FetchOrCreateOutlookEmailsRootScopeCommand,
  ],
})
export class UniqueModule {}
