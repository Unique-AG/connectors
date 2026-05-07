import { Smeared } from '../../utils/smeared';

export type RootScopeResolutionErrorCode =
  | 'unclaimed_name_match'
  | 'foreign_name_match'
  | 'ambiguous_name_match'
  | 'claim_failed'
  | 'invalid_parent'
  | 'invalid_site_name'
  | 'invalid_scope_kind';

export interface RootScopeResolutionErrorContext {
  siteId: string;
  // Optional because some error codes (e.g. `invalid_scope_kind`) describe a programmer error
  // that is independent of any specific parent scope — the caller invoked the wrong API for the
  // configured scope kind.
  parentScopeId?: string;
  siteName?: Smeared;
  detail?: string;
  cause?: unknown;
}

export class RootScopeResolutionError extends Error {
  public readonly code: RootScopeResolutionErrorCode;
  public readonly siteId: string;
  public readonly parentScopeId: string | undefined;
  public readonly siteName: Smeared | undefined;

  public constructor(code: RootScopeResolutionErrorCode, context: RootScopeResolutionErrorContext) {
    const parentSegment =
      context.parentScopeId === undefined ? '' : ` parent=${context.parentScopeId}`;
    const nameSegment = context.siteName === undefined ? '' : ` name=${context.siteName}`;
    const detail = context.detail ? ` — ${context.detail}` : '';
    const message = `[RootScopeResolutionError:${code}] site=${context.siteId}${parentSegment}${nameSegment}${detail}`;
    super(message, context.cause === undefined ? undefined : { cause: context.cause });
    this.name = 'RootScopeResolutionError';
    this.code = code;
    this.siteId = context.siteId;
    this.parentScopeId = context.parentScopeId;
    this.siteName = context.siteName;
  }
}
