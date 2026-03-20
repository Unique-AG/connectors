import z from 'zod';

export const UploadSessionSchema = z.object({ uploadUrl: z.string() });

// MS Graph requires chunks to be multiples of 320 KiB (327,680 bytes).
// 13 × 320 KiB = 4,160 KiB (~4 MB) — large enough to minimise round-trips
// without exceeding the recommended 4 MB per-chunk ceiling.
export const UPLOAD_CHUNK_SIZE = 13 * 327680;

export type ResolvedUniqueIdentity = { userId: string; companyId: string } | null;

export interface AttachmentFailure {
  fileName: string;
  reason: string;
}

export type AttachmentUploadResult =
  | { status: 'failed'; reason: AttachmentFailure }
  | { status: 'success' };
