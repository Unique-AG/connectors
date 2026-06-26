import { Injectable, Logger } from '@nestjs/common';
import { TranslateImmutableIdsToRestIdsQuery } from './translate-immutable-ids-to-rest-ids.query';

export interface WebLinkInput {
  /** Whether the id is a RestImmutableEntryId. If false, treated as a regular RestId. */
  isImmutable: boolean;
  id: string;
  /** Mailbox the message belongs to (email address). */
  mailbox: string;
  /**
   * Pre-existing webLink to return as-is for own-mailbox items.
   * Ignored for items in other mailboxes — those always get a freshly constructed OWA URL.
   */
  webLink: string;
}

/**
 * Builds working Outlook Web App (OWA) URLs for a batch of messages.
 *
 * ## Why this utility exists
 *
 * Since November 2025 Microsoft has been migrating tenants to their new cloud.microsoft domain.
 * After migration, every Graph API endpoint (GET, POST, search) returns webLinks in the new
 * format:
 *
 *   https://outlook.cloud.microsoft/mail/deeplink/read/{immutableId}?ItemID={immutableId}&…
 *
 * The new format embeds a **RestImmutableEntryId** (prefix `AAkA…`). However, the classic OWA
 * deep-link format — which is the only reliable way to open a message in a delegated or shared
 * mailbox — requires a **RestId** (prefix `AAMk…`) in its ItemID query parameter:
 *
 *   https://outlook.office365.com/owa/?ItemID={restId}&exvsurl=1&viewmodel=ReadMessageItem
 *
 * Passing a RestImmutableEntryId to OWA's ItemID parameter produces a broken link: OWA cannot
 * resolve it and the email fails to open. This affects ALL Graph responses on migrated tenants —
 * GET messages, POST createReplyAll, and the search index (once re-indexed after migration).
 *
 * ## What this utility does
 *
 * **Own mailbox** (`mailbox === userProfileEmail`): the stored webLink is returned as-is.
 * Own-mailbox webLinks work regardless of format because the user is opening their own Outlook
 * instance where both URL formats are supported.
 *
 * **Delegated / shared mailboxes**: the classic OWA URL is always constructed. For items whose
 * id is a RestImmutableEntryId (`isImmutable: true`) we first call the Graph
 * `translateExchangeIds` API to convert it to a RestId, then build the OWA URL with that RestId.
 * For items whose id is already a RestId (`isImmutable: false`) we build the URL directly.
 *
 * Results are batched per mailbox to minimise Graph API round-trips.
 *
 * Returns a Map keyed by `webLinkMapKey(mailbox, id)`.
 */

export function webLinkMapKey(mailbox: string, id: string): string {
  return `${mailbox}_${id}`;
}

@Injectable()
export class BuildWebLinksCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly translateImmutableIdsToRestIdsQuery: TranslateImmutableIdsToRestIdsQuery,
  ) {}

  public async run({
    userProfileId,
    userProfileEmail,
    ids,
  }: {
    userProfileId: string;
    userProfileEmail: string;
    ids: WebLinkInput[];
  }): Promise<Map<string, string>> {
    const result = new Map<string, string>();

    const delegatedByMailbox = new Map<string, WebLinkInput[]>();

    for (const item of ids) {
      if (item.mailbox === userProfileEmail) {
        result.set(webLinkMapKey(item.mailbox, item.id), item.webLink);
      } else {
        const bucket = delegatedByMailbox.get(item.mailbox) ?? [];
        bucket.push(item);
        delegatedByMailbox.set(item.mailbox, bucket);
      }
    }

    for (const [mailbox, items] of delegatedByMailbox.entries()) {
      const immutableItems = items.filter((i) => i.isImmutable);
      const restItems = items.filter((i) => !i.isImmutable);

      const immutableToRest =
        immutableItems.length > 0
          ? await this.translateImmutableIdsToRestIdsQuery.run({
              userProfileId,
              ids: immutableItems.map((i) => i.id),
              ownerEmail: mailbox,
            })
          : new Map<string, string>();

      for (const item of immutableItems) {
        const restId = immutableToRest.get(item.id);
        if (!restId) {
          this.logger.warn({ msg: 'ID translation missing — omitting web link', id: item.id });
          result.set(webLinkMapKey(item.mailbox, item.id), '');
        } else {
          result.set(webLinkMapKey(item.mailbox, item.id), this.buildOwaUrl(restId));
        }
      }

      for (const item of restItems) {
        result.set(webLinkMapKey(item.mailbox, item.id), this.buildOwaUrl(item.id));
      }
    }

    return result;
  }

  private buildOwaUrl(restId: string): string {
    return `https://outlook.office365.com/owa/?ItemID=${encodeURIComponent(restId)}&exvsurl=1&viewmodel=ReadMessageItem`;
  }
}
