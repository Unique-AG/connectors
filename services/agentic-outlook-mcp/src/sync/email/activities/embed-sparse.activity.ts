import { PointInput } from '../../../drizzle';

export interface IEmbedSparseActivity {
  embedSparse(payload: EmbedSparsePayload): Promise<PointInput[]>;
}

export interface EmbedSparsePayload {
  userProfileId: string;
  emailId: string;
  translatedSubject: string | null;
  translatedBody: string;
  summarizedBody: string | null;
  chunks: string[];
}
