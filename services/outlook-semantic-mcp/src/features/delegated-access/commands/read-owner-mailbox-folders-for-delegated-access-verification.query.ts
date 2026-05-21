import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import pLimit from 'p-limit';
import { isNumber } from 'remeda';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { isTokenExpiredError } from '~/utils/is-token-expired-error';
import { CannotReadErrorReason, DataAccessError } from '../utils/data-access-error';
import { isDelegatedAccessNotAvailableError } from '../utils/is-delegated-access-not-available-error';

export interface FolderNode {
  id: string;
  childFolderCount: number;
  childFolders?: FolderNode[];
}

@Injectable()
export class ReadOwnerMailboxFoldersFromMsGraphQuery {
  public async run(input: { client: Client; ownerEmail: string }): Promise<
    | {
        canRead: true;
        folderIds: string[];
      }
    | { canRead: false }
    | DataAccessError
  > {
    try {
      const folderIds = await this.readAllFolders(input);
      return { canRead: true, folderIds };
    } catch (error) {
      // This can only happen if the user lost all delegated access to the ownerEmail.
      if (isDelegatedAccessNotAvailableError(error)) {
        return { canRead: false };
      }

      const mapErrorToReason = (error: unknown): CannotReadErrorReason => {
        if (isTokenExpiredError(error)) {
          return CannotReadErrorReason.TokenExpired;
        }
        if (isRateLimitError(error)) {
          return CannotReadErrorReason.TransientError;
        }
        return CannotReadErrorReason.UnexpectedError;
      };

      return {
        reason: mapErrorToReason(error),
        error,
      };
    }
  }

  private async readAllFolders({
    client,
    ownerEmail,
  }: {
    client: Client;
    ownerEmail: string;
  }): Promise<string[]> {
    const readFolders = async (
      url: string,
      limit?: number,
    ): Promise<{ '@odata.nextLink'?: string; value: FolderNode[] }> => {
      let call = client.api(url);
      if (isNumber(limit)) {
        call = call.top(limit);
      }
      return await call.header('Prefer', 'IdType="ImmutableId"').get();
    };

    const fetchChildFolders = async (folderId: string): Promise<FolderNode[]> => {
      const children: FolderNode[] = [];

      let response = await readFolders(
        `/users/${ownerEmail}/mailFolders/${folderId}/childFolders`,
        500,
      );
      children.push(...(response?.value ?? []));

      while (response?.['@odata.nextLink']) {
        response = await readFolders(response['@odata.nextLink']);
        children.push(...(response?.value ?? []));
      }

      return children;
    };

    const limit = pLimit(10);
    const expandRecursive = async (folder: FolderNode): Promise<void> => {
      if (!folder.childFolderCount) {
        return;
      }

      folder.childFolders = await limit(() => fetchChildFolders(folder.id));
      await Promise.all(folder.childFolders.map(expandRecursive));
    };

    const rootFolders: FolderNode[] = [];
    let response = await client
      .api(`/users/${ownerEmail}/mailFolders`)
      .header('Prefer', 'IdType="ImmutableId"')
      .top(500)
      .get();
    rootFolders.push(...(response?.value ?? []));

    while (response?.['@odata.nextLink']) {
      response = await client
        .api(response['@odata.nextLink'])
        .header('Prefer', 'IdType="ImmutableId"')
        .get();
      rootFolders.push(...(response?.value ?? []));
    }

    await Promise.all(rootFolders.map(expandRecursive));

    const flattenFolders = (items: FolderNode[]): Array<string> =>
      items.flatMap((item) => [item.id, ...flattenFolders(item.childFolders ?? [])]);

    return flattenFolders(rootFolders);
  }
}
