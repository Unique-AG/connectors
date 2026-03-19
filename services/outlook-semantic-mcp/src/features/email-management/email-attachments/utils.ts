import z from 'zod';

export const UploadSessionSchema = z.object({ uploadUrl: z.string() });

export const UPLOAD_CHUNK_SIZE = 13 * 327680; // 4,259,840 bytes — must be a multiple of 320 KiB (327,680) per MS Graph API requirement

export type ResolvedUniqueIdentity = { userId: string; companyId: string } | null;

export interface AttachmentFailure {
  fileName: string;
  reason: string;
}
