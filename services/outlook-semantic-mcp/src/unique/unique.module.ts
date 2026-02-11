import { Module } from "@nestjs/common";
import { DrizzleModule } from "../drizzle/drizzle.module";
import { UniqueService } from "./unique.service";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "./unique-scopes/fetch-or-create-outlook-emails-root-scope.command";

@Module({
  imports: [DrizzleModule],
  providers: [UniqueService, FetchOrCreateOutlookEmailsRootScopeCommand],
  exports: [UniqueService, FetchOrCreateOutlookEmailsRootScopeCommand],
})
export class UniqueModule {}
