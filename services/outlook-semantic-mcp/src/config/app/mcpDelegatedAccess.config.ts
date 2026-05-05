import { z } from 'zod/v4';

// Send as (‎0‎)
// The Send as permission allows the delegate to send an email from this mailbox. Message will appear to have been sent from this mailbox owner.
// Send on behalf (‎0‎)
// The Send on Behalf permission allows the delegate to send email on behalf of this mailbox. The From line in any message sent by a delegate indicates that the message was sent by the delegate on behalf of the mailbox owner.
// Read and manage (Full Access) (‎0‎)
// The Full Access permission allows a delegate to open this mailbox and behave as the mailbox owner.

const delegatedAccessDiscoveryCronSchedule = z
  .string()
  .prefault('0 */6 * * *')
  .describe('Cron schedule for delegated access discovery. Default: every 6 hours (4x/day).');

const disabledDelegatedAccessScan = z.object({
  delegatedAccessScan: z.literal('disabled'),
});

const onlyFullDelegatedAccessScanConfig = z.object({
  // On microsoft exchange: https://admin.exchange.microsoft.com/#/mailboxes
  // You can set Read and manage (Full Access) on a mailbox - if a user has read and manage set up there
  // he get's full delegated access over that mailbox. This means that he can access the following endpoints as a
  // delegated.
  // /users/{{email}}/messages
  // /users/{{email}}/mailFolders
  // /users/{{email}}/mailFolders/{{folderId}}/messages
  // When we configure the delegated access to be fullAccessOnly we will call /users/{{email}}/messages and assume
  // the user has full access to that inbox.
  delegatedAccessScan: z.literal('fullAccessOnly'),
  delegatedAccessDiscoveryCronSchedule,
});

const granularDelegatedAccessScanConfig = z.object({
  // The granular access mode is designed to for cases when users share individual folders between them. Basically
  // If user Alice shares "Inbox" and "RFQ" folders with user Bob the following endpoints can be accessed using
  // delegated access.
  // /users/{{email}}/mailFolders => will list the folders from Alice which are shared with Bob
  // /users/{{email}}/mailFolders/{{folderId}}/messages => we can read messages from the folder
  // The following endpoints are not accesible:
  // /users/{{email}}/messages
  // In this mode unfortunately we cannot rely on a folder listing alone to see if you have access to a folder becase
  // of the following case.
  // Alice has the following directory structure.
  // "Inbox" -> "RFQ" - the "RFQ" is a child of "Inbox" and she shares with Bob only the "RFQ" folder. When we call
  // /users/{{email}}/mailFolders => we can list both folders "Inbox" and "RFQ" but we can only read messages from the "RFQ"
  // folder.
  delegatedAccessScan: z.literal('granularAccess'),
  delegatedAccessDiscoveryCronSchedule,
  delegatedAccessVerificationCronSchedule: z
    .string()
    .prefault('0 */4 * * *')
    .describe('Cron schedule for delegated access verification. Default: every 4 hours (6x/day).'),
});

export const delegatedAccessConfig = z.discriminatedUnion('delegatedAccessScan', [
  disabledDelegatedAccessScan,
  onlyFullDelegatedAccessScanConfig,
  granularDelegatedAccessScanConfig,
]);
