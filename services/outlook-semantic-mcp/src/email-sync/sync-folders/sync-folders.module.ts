import { Module, Provider } from "@nestjs/common";
import { DrizzleModule } from "~/drizzle/drizzle.module";
import { MsGraphModule } from "~/msgraph/msgraph.module";
import { UniqueModule } from "~/unique/unique.module";
import { SyncFoldersCommand } from "./commands/sync-system-folders.command";

const COMMANDS: Provider[] = [SyncFoldersCommand];

const QUERIES: Provider[] = [];

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule],
  providers: [...COMMANDS, ...QUERIES],
  exports: [...COMMANDS, ...QUERIES],
})
export class SyncFoldersModule {}
