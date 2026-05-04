import { createSmeared, smearPath } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import pLimit from 'p-limit';
import { clone, sumBy, unique } from 'remeda';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { GraphOutlookDirectory, graphOutlookDirectoriesResponse } from './microsoft-graph.dtos';

@Injectable()
export class FetchAllDirectoriesFromOutlookQuery {
  private readonly logger = new Logger(FetchAllDirectoriesFromOutlookQuery.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(userProfileId: string): Promise<GraphOutlookDirectory[]> {
    traceAttrs({ userProfileId: userProfileId });
    this.logger.log({ userProfileId, msg: `Fetching all directories from Outlook` });

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    const rootDirectories: GraphOutlookDirectory[] = await this.fetchAllDirectories({
      apiUrl: `me/mailFolders`,
      client,
    });

    traceEvent('root directories fetched', { count: rootDirectories.length });
    this.logger.log({
      userProfileId,
      rootDirectoryCount: rootDirectories.length,
      msg: `Root directories fetched`,
    });
    this.logFullDirectoriesStructure({
      userProfileId,
      directories: rootDirectories,
      msg: `Directories from microsoft before expansion`,
    });

    const limit = pLimit(10);
    const expandDirectoryRecursive = async (directory: GraphOutlookDirectory): Promise<void> => {
      if (!directory.childFolderCount) {
        return;
      }

      directory.childFolders = await limit(() =>
        this.fetchChildDirectories({
          parentDirectoryId: directory.id,
          client,
        }),
      );
      await Promise.all(directory.childFolders.map(expandDirectoryRecursive));
    };

    await Promise.all(rootDirectories.map(expandDirectoryRecursive));
    this.logFullDirectoriesStructure({
      userProfileId,
      directories: rootDirectories,
      msg: `Directories from microsoft after expansion`,
    });

    const totalCount = this.countDirectories(rootDirectories);
    const pathsFetched = this.getPaths(rootDirectories, []);
    const directoriesTree = pathsFetched.map((item) => smearPath(createSmeared(item))).join('\r\n');
    traceEvent('all directories fetched', {
      totalCount: totalCount,
      rootDirectoriesCount: rootDirectories.length,
      directoriesTree,
    });
    this.logger.log({
      userProfileId,
      totalCount,
      rootDirectoriesCount: rootDirectories.length,
      directoriesTree,
      msg: `All directories fetched including children`,
    });

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
      .query({ includeHiddenFolders: 'true' })
      .top(500)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .get();
    let parsedResult = graphOutlookDirectoriesResponse.parse(graphResponse);
    const output: GraphOutlookDirectory[] = parsedResult.value;
    let pageCount = 1;

    while (parsedResult['@odata.nextLink']) {
      pageCount++;
      graphResponse = await client
        .api(parsedResult['@odata.nextLink'])
        .header(`Prefer`, `IdType="ImmutableId"`)
        .get();
      parsedResult = graphOutlookDirectoriesResponse.parse(graphResponse);
      output.push(...parsedResult.value);
      traceEvent('directories page fetched', { page: pageCount, runningTotal: output.length });
    }

    return output;
  }

  private countDirectories(directories: GraphOutlookDirectory[]): number {
    return sumBy(
      directories,
      (dir) => 1 + (dir.childFolders ? this.countDirectories(dir.childFolders) : 0),
    );
  }

  private getPaths(directories: GraphOutlookDirectory[], parent: string[]): string[] {
    return unique(
      directories.flatMap((directory) => {
        const currentPath = [...parent, directory.displayName];
        return [currentPath.join('/'), ...this.getPaths(directory.childFolders ?? [], currentPath)];
      }),
    );
  }

  private logFullDirectoriesStructure({
    msg,
    userProfileId,
    directories,
  }: {
    userProfileId: string;
    directories: GraphOutlookDirectory[];
    msg: string;
  }): void {
    const frozenValue = clone(directories);

    const mapRecursive = (items: GraphOutlookDirectory[]): GraphOutlookDirectory[] => {
      return items.map((item) => ({
        ...item,
        displayName: createSmeared(item.displayName).toString(),
        childFolders: mapRecursive(item.childFolders ?? []),
      }));
    };

    this.logger.debug({
      msg,
      userProfileId,
      directoriesStructure: mapRecursive(frozenValue),
    });
  }

  private async fetchChildDirectories({
    parentDirectoryId,
    client,
  }: {
    parentDirectoryId: string;
    client: Client;
  }): Promise<GraphOutlookDirectory[]> {
    let graphResponse = await client
      .api(`me/mailFolders/${parentDirectoryId}/childFolders`)
      .query({ includeHiddenFolders: 'true' })
      .top(500)
      .header(`Prefer`, `IdType="ImmutableId"`)
      .get();
    let parsedResult = graphOutlookDirectoriesResponse.parse(graphResponse);
    const output: GraphOutlookDirectory[] = [...parsedResult.value];

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
