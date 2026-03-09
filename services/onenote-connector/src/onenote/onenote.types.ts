import { z } from 'zod';

export const NotebookSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  createdDateTime: z.string(),
  lastModifiedDateTime: z.string(),
  isShared: z.boolean().optional(),
  userRole: z.enum(['Owner', 'Contributor', 'Reader', 'None']).optional(),
  links: z
    .object({
      oneNoteClientUrl: z.object({ href: z.string() }).optional(),
      oneNoteWebUrl: z.object({ href: z.string() }).optional(),
    })
    .optional(),
});
export type Notebook = z.infer<typeof NotebookSchema>;

export const SectionSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  createdDateTime: z.string(),
  lastModifiedDateTime: z.string(),
  isDefault: z.boolean().optional(),
  links: z
    .object({
      oneNoteClientUrl: z.object({ href: z.string() }).optional(),
      oneNoteWebUrl: z.object({ href: z.string() }).optional(),
    })
    .optional(),
});
export type Section = z.infer<typeof SectionSchema>;

export const SectionGroupSchema = z.object({
  id: z.string(),
  displayName: z.string(),
  createdDateTime: z.string(),
  lastModifiedDateTime: z.string(),
});
export type SectionGroup = z.infer<typeof SectionGroupSchema>;

export const PageSchema = z.object({
  id: z.string(),
  title: z.string().nullable().optional(),
  createdDateTime: z.string(),
  lastModifiedDateTime: z.string(),
  contentUrl: z.string().optional(),
  links: z
    .object({
      oneNoteClientUrl: z.object({ href: z.string() }).optional(),
      oneNoteWebUrl: z.object({ href: z.string() }).optional(),
    })
    .optional(),
});
export type Page = z.infer<typeof PageSchema>;

export const DriveItemDeltaSchema = z.object({
  id: z.string(),
  name: z.string().optional(),
  file: z.object({ mimeType: z.string().optional() }).optional(),
  package: z.object({ type: z.string() }).optional(),
  folder: z.object({ childCount: z.number().optional() }).optional(),
  parentReference: z
    .object({
      driveId: z.string().optional(),
      id: z.string().optional(),
      path: z.string().optional(),
    })
    .optional(),
  deleted: z.object({ state: z.string().optional() }).optional(),
  lastModifiedDateTime: z.string().optional(),
});
export type DriveItemDelta = z.infer<typeof DriveItemDeltaSchema>;

export const PermissionIdentitySchema = z.object({
  displayName: z.string().optional(),
  email: z.string().optional(),
  id: z.string().optional(),
});

export const DrivePermissionSchema = z.object({
  id: z.string().optional(),
  roles: z.array(z.string()).optional(),
  grantedToV2: z
    .object({
      user: PermissionIdentitySchema.optional(),
      group: PermissionIdentitySchema.optional(),
    })
    .optional(),
  grantedToIdentitiesV2: z
    .array(
      z.object({
        user: PermissionIdentitySchema.optional(),
        group: PermissionIdentitySchema.optional(),
      }),
    )
    .optional(),
});
export type DrivePermission = z.infer<typeof DrivePermissionSchema>;

export const GroupMemberSchema = z.object({
  id: z.string(),
  displayName: z.string().optional(),
  mail: z.string().optional(),
  userPrincipalName: z.string().optional(),
});
export type GroupMember = z.infer<typeof GroupMemberSchema>;
