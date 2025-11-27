import type { ICleanupActivity } from './cleanup.activity';
import type { ICreateChunksActivity } from './create-chunks.activity';
import type { IEmbedDenseActivity } from './embed-dense.activity';
import type { IEmbedSparseActivity } from './embed-sparse.activity';
import type { IIndexActivity } from './index.activity';
import type { ILoadEmailActivity } from './load-email.activity';
import type { ISaveEmailResultsActivity } from './save-email-results.activity';
import type { ISavePointsActivity } from './save-points.activity';
import type { ISummarizeBodyActivity } from './summarize-body.activity';
import type { ISummarizeThreadActivity } from './summarize-thread.activity';
import type { ITranslateActivity } from './translate.activity';
import type { IUpdateStatusActivity } from './update-status.activity';

export type Activities = ILoadEmailActivity &
  ISaveEmailResultsActivity &
  ICreateChunksActivity &
  IUpdateStatusActivity &
  ICleanupActivity &
  ITranslateActivity &
  ISummarizeBodyActivity &
  ISummarizeThreadActivity &
  IEmbedDenseActivity &
  IEmbedSparseActivity &
  ISavePointsActivity &
  IIndexActivity;
