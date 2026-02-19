import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import {
  GraphOutlookDirectory,
  graphOutlookDirectoriesResponse,
  graphOutlookDirectory,
} from './microsoft-graph.dtos';

@Injectable()
export class FetchAllDirectoriesFromOutlookQuery {
  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: string): Promise<GraphOutlookDirectory[]> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const rootDirectories: GraphOutlookDirectory[] = await this.fetchAllDirectories({
      apiUrl: `me/mailFolders`,
      client,
    });

    traceEvent('directories fetched', { count: rootDirectories.length });

    const shouldExpandDirectory = (directory: GraphOutlookDirectory) =>
      directory.childFolderCount > 0 &&
      (!directory.childFolders || directory.childFolders.length !== directory.childFolderCount);

    const expandDirectoryRecursive = async (directory: GraphOutlookDirectory): Promise<void> => {
      if (!shouldExpandDirectory(directory)) {
        return;
      }

      const expanded = await this.expandDirectory({
        parentDirectoryId: directory.id,
        client,
      });
      directory.childFolders = expanded.childFolders;
      const promises =
        directory.childFolders?.map((child) => {
          if (shouldExpandDirectory(child)) {
            return expandDirectoryRecursive(child);
          }
          return Promise.resolve();
        }) ?? [];
      await Promise.all(promises);
    };

    const allPromisses: Promise<void>[] = [];
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

  private async expandDirectory({
    parentDirectoryId,
    client,
  }: {
    parentDirectoryId: string;
    client: Client;
  }): Promise<GraphOutlookDirectory> {
    const response = await client
      .api(`me/mailFolders/${parentDirectoryId}`)
      .top(500)
      .expand('childFolders')
      .header(`Prefer`, `IdType="ImmutableId"`)
      .get();
    return graphOutlookDirectory.parseAsync(response);
  }
}
