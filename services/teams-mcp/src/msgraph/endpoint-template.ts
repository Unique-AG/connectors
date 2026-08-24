// Graph paths carry real identifiers, and some of them identify people: a 1:1
// chat id is `19:<oid>_<oid>@unq.gbl.spaces` and embeds both participants' Entra
// object ids. A metric label is retained and queryable, so the raw path must
// never reach one — and every distinct id would also be its own time series.
//
// Matching is against an explicit list of the routes this service calls, and an
// unmatched path collapses to `UNKNOWN_ENDPOINT`. A route added later therefore
// reports as unknown rather than leaking an id by default.

export const UNKNOWN_ENDPOINT = '/unknown';

// `/me` and `/users/:userId` are interchangeable prefixes on the meeting routes:
// `/me` for the on-demand delegated path, `/users/:userId` for the webhook path.
const MEETING_OWNERS = ['/me', '/users/:userId'] as const;

const MEETING_ROUTES = [
  '/onlineMeetings',
  '/onlineMeetings/:meetingId',
  '/onlineMeetings/:meetingId/recordings',
  '/onlineMeetings/:meetingId/recordings/:recordingId/content',
  '/onlineMeetings/:meetingId/transcripts',
  '/onlineMeetings/:meetingId/transcripts/:transcriptId',
  '/onlineMeetings/:meetingId/transcripts/:transcriptId/content',
] as const;

const ENDPOINT_TEMPLATES: readonly string[] = [
  '/me/chats',
  '/me/joinedTeams',
  '/search/query',
  '/subscriptions',
  '/subscriptions/:subscriptionId',
  '/chats/:chatId/messages',
  '/chats/:chatId/messages/:messageId',
  '/teams/:teamId/channels',
  '/teams/:teamId/channels/:channelId/messages',
  '/teams/:teamId/channels/:channelId/messages/:messageId',
  ...MEETING_OWNERS.flatMap((owner) => MEETING_ROUTES.map((route) => `${owner}${route}`)),
];

function toPattern(template: string): RegExp {
  const escaped = template.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`^${escaped.replace(/:[A-Za-z]+/g, '[^/]+')}$`);
}

const PATTERNS: readonly { pattern: RegExp; template: string }[] = ENDPOINT_TEMPLATES.map(
  (template) => ({ pattern: toPattern(template), template }),
);

/**
 * Reduces a Graph request path to a bounded, id-free label.
 *
 * Strips the API version, then returns the matching route template (for example
 * `/chats/:chatId/messages/:messageId`). Anything unrecognised — including a
 * malformed URL — returns {@link UNKNOWN_ENDPOINT}.
 */
export function templateEndpoint(url: string): string {
  let pathname: string;
  try {
    pathname = new URL(url).pathname;
  } catch {
    return UNKNOWN_ENDPOINT;
  }

  // Graph versions its routes as `/v1.0` or `/beta`; SearchService can be flipped
  // to beta, so both must strip to the same label.
  const path = pathname.replace(/^\/(v\d+(\.\d+)?|beta)/, '').replace(/\/$/, '');

  return PATTERNS.find(({ pattern }) => pattern.test(path))?.template ?? UNKNOWN_ENDPOINT;
}
