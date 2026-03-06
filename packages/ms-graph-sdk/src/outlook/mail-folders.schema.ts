import z from 'zod/v4';

export interface MailFolder {
  id: string;
  displayName: string;
  parentFolderId?: string;
  childFolderCount?: number;
  totalItemCount?: number;
  unreadItemCount?: number;
  isHidden?: boolean;
  childFolders?: MailFolder[];
}

/**
 * Represents a mail folder in a user's mailbox.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0
 */
export const MailFolder: z.ZodType<MailFolder> = z.lazy(() =>
  z.object({
    id: z.string(),
    displayName: z.string(),
    parentFolderId: z.string().optional(),
    childFolderCount: z.number().optional(),
    totalItemCount: z.number().optional(),
    unreadItemCount: z.number().optional(),
    isHidden: z.boolean().optional(),
    childFolders: z.array(MailFolder).optional(),
  }),
);
