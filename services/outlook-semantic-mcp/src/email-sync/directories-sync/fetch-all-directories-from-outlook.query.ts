import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { GraphOutlookDirectory, graphOutlookDirectoriesResponse } from './microsoft-graph.dtos';

@Injectable()
export class FetchAllDirectoriesFromOutlookQuery {
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  public async run(userProfileId: string): Promise<GraphOutlookDirectory[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const rootDirectories: GraphOutlookDirectory[] = await this.fetchAllDirectories({
      apiUrl: `mailFolders`,
      client,
    });

    const shouldExpandDirectory = (directory: GraphOutlookDirectory) =>
      directory.childFolderCount > 0 &&
      (!directory.childFolders || directory.childFolders.length !== directory.childFolderCount);

    const allPromisses: Promise<void>[] = [];

    const expandDirectoryRecursive = async (directory: GraphOutlookDirectory): Promise<void> => {
      if (!shouldExpandDirectory(directory)) {
        return;
      }

      directory.childFolders = await this.fetchAllDirectories({
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

  private async fetchAllDirectories({
    apiUrl,
    client,
  }: {
    apiUrl: string;
    client: Client;
  }): Promise<GraphOutlookDirectory[]> {
    let graphResponse = await client
      .api(apiUrl)
      .top(500)
      .expand('childFolders')
      .header(`Prefer`, `IdType="ImmutableId"`)
      .get();
    let parsedResult = graphOutlookDirectoriesResponse.parse(graphResponse);
    const output: GraphOutlookDirectory[] = parsedResult.value;

    while (parsedResult['@odata.nextLink']) {
      graphResponse = await client
        .api(parsedResult['@odata.nextLink'])
        .header(`Prefer`, `IdType="ImmutableId"`)
        .get();
      parsedResult = graphOutlookDirectoriesResponse.parse(graphResponse);
      output.push(...parsedResult.value);
    }

    return output;
  }
}
