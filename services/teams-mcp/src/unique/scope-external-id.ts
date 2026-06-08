export const EXTERNAL_ID_PREFIX = 'teams:' as const;

/**
 * Builds the deterministic externalId for a meeting (subject) scope.
 *
 * Anchored on the Graph onlineMeeting id so recurring meetings share the same
 * parent scope. `encodeURIComponent` is required because Graph ids are base64-ish
 * and can contain `/`, `+`, `=`, which would collide with the `/` delimiter.
 */
export function buildMeetingExternalId(meetingId: string): string {
  return `${EXTERNAL_ID_PREFIX}${encodeURIComponent(meetingId)}/meeting`;
}

/**
 * Builds the deterministic externalId for an occurrence (session) scope.
 *
 * Anchored on the transcript id so each recording session gets its own child
 * scope, even for multiple meetings on the same day. Re-ingesting re-stamps the
 * same externalId (idempotent).
 */
export function buildOccurrenceExternalId(meetingId: string, transcriptId: string): string {
  return `${EXTERNAL_ID_PREFIX}${encodeURIComponent(meetingId)}/occurrence:${encodeURIComponent(transcriptId)}`;
}
