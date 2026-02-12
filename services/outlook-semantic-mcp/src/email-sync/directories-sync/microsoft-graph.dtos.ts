import z from 'zod/v4';

const graphOutlookDirectoryBaseSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  childFolderCount: z.number().int().nonnegative(),
  totalItemCount: z.number().int().nonnegative(),
  unreadItemCount: z.number().int().nonnegative(),
  parentFolderId: z.string(),
  isHidden: z.boolean().optional().default(false),
});

export interface GraphOutlookDirectory {
  id: string;
  displayName: string;
  childFolderCount: number;
  totalItemCount: number;
  unreadItemCount: number;
  parentFolderId: string;
  isHidden?: boolean;
  childFolders?: GraphOutlookDirectory[];
}

export const graphOutlookDirectory: z.ZodType<GraphOutlookDirectory> =
  graphOutlookDirectoryBaseSchema.extend({
    childFolders: z.lazy(() => z.array(graphOutlookDirectory)).optional(),
  });

export const graphOutlookDirectoriesResponse = z.object({
  '@odata.context': z.string().optional(),
  value: z.array(graphOutlookDirectory),
  '@odata.nextLink': z.string().optional(),
});
