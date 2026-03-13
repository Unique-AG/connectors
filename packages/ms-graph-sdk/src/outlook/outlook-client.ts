import { buildUrl, ODataCollection } from '../shared/odata';
import type { DeltaResponse, GraphPagedResponse } from '../shared/pagination';
import { paginate, paginateDelta } from '../shared/pagination';
import { MailFolder } from './mail-folders.schema';
import { Message } from './messages.schema';
import {
  CreateMessageRequest,
  GetMailFolderRequest,
  GetMailFoldersDeltaRequest,
  GetMessageRequest,
  GetSystemFolderRequest,
  ListMailFoldersRequest,
  ListMessagesRequest,
} from './outlook.requests';
import { OutlookCategory } from './outlook-category.schema';

export type {
  CreateMessageRequest,
  GetMailFolderRequest,
  GetMailFoldersDeltaRequest,
  GetMessageRequest,
  GetSystemFolderRequest,
  ListMailFoldersRequest,
  ListMessagesRequest,
} from './outlook.requests';
export type { OutlookCategory } from './outlook-category.schema';

const IMMUTABLE_IDS_HEADER = { Prefer: 'IdType="ImmutableId"' } as const;

export class OutlookClient {
  public constructor(private readonly fetch: typeof globalThis.fetch) {}

  /**
   * Get the mail folder collection directly under the root folder of the signed-in user.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/user-list-mailfolders?view=graph-rest-1.0
   */
  public listMailFolders(params: ListMailFoldersRequest = {}): GraphPagedResponse<MailFolder> {
    const { immutableIds, ...odata } = params;
    const url = buildUrl('/me/mailFolders', odata);
    const headers = immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    return paginate(this.fetch, url, MailFolder, headers ? { headers } : undefined);
  }

  /**
   * Retrieve the properties and relationships of a mail folder object.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0
   */
  public async getMailFolder(params: GetMailFolderRequest): Promise<MailFolder> {
    const url = buildUrl(`/me/mailFolders/${params.folderId}`, { $expand: params.expand });
    const headers = params.immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    const response = await this.fetch(url, headers ? { headers } : undefined);
    return MailFolder.parse(await response.json());
  }

  /**
   * Retrieve a mail folder by its well-known folder name (e.g. inbox, drafts, sentitems).
   *
   * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-get?view=graph-rest-1.0
   */
  public async getSystemFolder(params: GetSystemFolderRequest): Promise<MailFolder> {
    const headers = params.immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    const response = await this.fetch(
      `/me/mailFolders/${params.folderName}`,
      headers ? { headers } : undefined,
    );
    return MailFolder.parse(await response.json());
  }

  /**
   * Get a set of mail folders that have been added, deleted, or removed from the user's mailbox.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/mailfolder-delta?view=graph-rest-1.0
   */
  public getMailFoldersDelta(params: GetMailFoldersDeltaRequest = {}): DeltaResponse<MailFolder> {
    const url = params.deltaLink ?? '/me/mailFolders/delta';
    const headers = params.immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    return paginateDelta(this.fetch, url, MailFolder, headers ? { headers } : undefined);
  }

  /**
   * Get all the categories that have been defined for the signed-in user.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/outlookuser-list-mastercategories?view=graph-rest-1.0
   */
  public async listMasterCategories(): Promise<OutlookCategory[]> {
    const response = await this.fetch('/me/outlook/masterCategories');
    return ODataCollection(OutlookCategory).parse(await response.json()).value;
  }

  /**
   * Retrieve the properties and relationships of a message object.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/message-get?view=graph-rest-1.0
   */
  public async getMessage(params: GetMessageRequest): Promise<Message> {
    const url = buildUrl(`/me/messages/${params.messageId}`, { $select: params.select });
    const headers = params.immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    const response = await this.fetch(url, headers ? { headers } : undefined);
    return Message.parse(await response.json());
  }

  /**
   * Get the messages in the signed-in user's mailbox, including the Deleted Items and Clutter folders.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/user-list-messages?view=graph-rest-1.0
   */
  public listMessages(params: ListMessagesRequest = {}): GraphPagedResponse<Message> {
    const { immutableIds, ...odata } = params;
    const url = buildUrl('/me/messages', odata);
    const headers = immutableIds ? IMMUTABLE_IDS_HEADER : undefined;
    return paginate(this.fetch, url, Message, headers ? { headers } : undefined);
  }

  /**
   * Create a draft of a new message in JSON format. The draft is saved in the Drafts folder.
   *
   * @see https://learn.microsoft.com/en-us/graph/api/user-post-messages?view=graph-rest-1.0
   */
  public async createDraft(params: CreateMessageRequest): Promise<Message> {
    const response = await this.fetch('/me/messages', {
      method: 'POST',
      body: JSON.stringify(CreateMessageRequest.parse(params)),
    });
    return Message.parse(await response.json());
  }
}
