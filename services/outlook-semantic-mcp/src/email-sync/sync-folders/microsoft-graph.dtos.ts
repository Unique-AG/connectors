import z from "zod/v4";

const graphMailFolderBaseSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  childFolderCount: z.number().int().nonnegative(),
  totalItemCount: z.number().int().nonnegative(),
  unreadItemCount: z.number().int().nonnegative(),
  parentFolderId: z.string(),
  isHidden: z.boolean().optional().default(false),
});

export interface GraphMailFolder {
  id: string;
  displayName: string;
  childFolderCount: number;
  totalItemCount: number;
  unreadItemCount: number;
  parentFolderId: string;
  isHidden?: boolean;
  childFolders?: GraphMailFolder[];
}

export const graphMailFolderSchema: z.ZodType<GraphMailFolder> =
  graphMailFolderBaseSchema.extend({
    childFolders: z.lazy(() => z.array(graphMailFolderSchema)).optional(),
  });

export const graphMailFoldersSchema = z.object({
  "@odata.context": z.string().optional(),
  value: z.array(graphMailFolderSchema),
  "@odata.nextLink": z.string().optional(),
});

// export type GraphMailFolder = z.infer<typeof graphMailFolderSchema>;
