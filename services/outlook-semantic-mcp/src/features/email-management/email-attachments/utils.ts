import z from 'zod';

export const UploadSessionSchema = z.object({ uploadUrl: z.string() });

// MS Graph requires chunks to be multiples of 320 KiB (327,680 bytes) and
// recommends a maximum of 4 MiB (4,194,304 bytes) per PUT request.
// 12 × 320 KiB = 3,840 KiB (3,932,160 bytes) — stays within that ceiling.
export const UPLOAD_CHUNK_SIZE = 12 * 327680;

export type ResolvedUniqueIdentity = { userId: string; companyId: string } | null;

export interface AttachmentFailure {
  fileName: string;
  reason: string;
}

export type AttachmentUploadResult =
  | { status: 'failed'; reason: AttachmentFailure }
  | { status: 'success' };
