import { createHash } from 'node:crypto';

/**
 * De-identifies an email address for logs and spans.
 *
 * The local part is hashed so the same person still correlates across log lines — which matters
 * for addresses that have no userProfileId to group by, such as a calendar owner or a getSchedule
 * attendee. The domain is kept because cross-tenant mix-ups are a real failure mode here (see the
 * MailboxInfoStale note in is-delegated-access-not-available-error).
 *
 * This is de-identification, not encryption: the hash is unsalted, so a known address can be
 * confirmed by hashing it. It keeps addresses out of the log aggregator in plaintext and stops
 * them being searchable by email; it is not a defence against a determined attacker.
 */
export function obfuscateEmail(email: string): string;
export function obfuscateEmail(email: string | null | undefined): string | undefined;
export function obfuscateEmail(email: string | null | undefined): string | undefined {
  if (email === null || email === undefined) {
    return undefined;
  }
  const trimmed = email.trim();
  if (trimmed === '') {
    return undefined;
  }
  const at = trimmed.lastIndexOf('@');
  const local = at === -1 ? trimmed : trimmed.slice(0, at);
  const digest = createHash('sha256').update(local.toLowerCase()).digest('hex').slice(0, 12);
  return at === -1 ? digest : `${digest}@${trimmed.slice(at + 1)}`;
}
