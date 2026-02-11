import { Injectable } from "@nestjs/common";
import {
  GraphMailFolder,
  graphMailFoldersSchema,
} from "./microsoft-graph.dtos";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import { Client } from "@microsoft/microsoft-graph-client";

@Injectable()
export class FetchAllFodlersFromMicrosoftGraphQuery {
  constructor(private graphClientFactory: GraphClientFactory) {}

  public async run(userProfileId: string): Promise<GraphMailFolder[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const rootDirectories: GraphMailFolder[] = await this.fetchAll({
      apiUrl: `mailFolders`,
      client,
    });

    const shouldExpandDirectory = (directory: GraphMailFolder) =>
      directory.childFolderCount > 0 &&
      (!directory.childFolders ||
        directory.childFolders.length !== directory.childFolderCount);

    const allPromisses: Promise<void>[] = [];

    const expandDirectoryRecursive = async (
      directory: GraphMailFolder,
    ): Promise<void> => {
      if (!shouldExpandDirectory(directory)) {
        return;
      }

      directory.childFolders = await this.fetchAll({
        apiUrl: `mailFolders/${directory.id}`,
        client,
      });
      directory.childFolders.forEach((child) => {
        if (shouldExpandDirectory(child)) {
          allPromisses.push(expandDirectoryRecursive(child));
        }
      });
    };

    rootDirectories.forEach((rootDirectory) => {
      // Roots are already expanded.
      rootDirectory.childFolders?.forEach((subChild) => {
        if (shouldExpandDirectory(subChild)) {
          allPromisses.push(expandDirectoryRecursive(subChild));
        }
      });
    });

    await Promise.all(allPromisses);
    return rootDirectories;
  }

  private async fetchAll({
    apiUrl,
    client,
  }: {
    apiUrl: string;
    client: Client;
  }): Promise<GraphMailFolder[]> {
    const results: GraphMailFolder[] = [];
    let nextLink: string | null = null;
    do {
      const directories = await client
        .api(apiUrl)
        .top(500)
        .expand("childFolders")
        .header(`Prefer`, `IdType="ImmutableId"`)
        .get();
      const parsed = graphMailFoldersSchema.parse(directories);
      results.push(...parsed.value);
      nextLink = parsed["@odata.nextLink"] ?? null;
    } while (nextLink);

    return results;
  }
}
