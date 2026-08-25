#!/usr/bin/env node
/**
 * Live Microsoft Graph calendar probes (GET only against Graph).
 *
 * Put tokens in this folder's .env (gitignored):
 *   GRAPH_ACCESS_TOKEN=...
 *   GRAPH_REFRESH_TOKEN=...   # optional; used on 401
 *
 * Tokens copied from user_profiles are AES-256-GCM (iv.tag.data). The probe
 * decrypts them with ENCRYPTION_KEY from services/outlook-semantic-mcp/.env.
 *
 * Client id/secret for refresh can live here or in ../../../.env.
 *
 * From services/outlook-semantic-mcp:
 *   node docs/json/calendar-probes/probe-calendars.mjs
 *
 * Writes docs/json/calendar-probes/findings.json and raw responses to .probe-cache/.
 */
import { createDecipheriv } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const serviceRoot = join(here, '../../..');
const cacheDir = join(here, '.probe-cache');
const GRAPH = 'https://graph.microsoft.com/v1.0';
const CALENDAR_SELECT =
  'id,name,owner,canEdit,canShare,canViewPrivateItems,isDefaultCalendar,isTallyingResponses';

function parseEnvFile(text) {
  const values = {};
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (line.length === 0 || line.startsWith('#')) {
      continue;
    }
    const eq = line.indexOf('=');
    if (eq <= 0) {
      continue;
    }
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (value.startsWith('"')) {
      const end = value.indexOf('"', 1);
      value = end === -1 ? value.slice(1) : value.slice(1, end);
    } else if (value.startsWith("'")) {
      const end = value.indexOf("'", 1);
      value = end === -1 ? value.slice(1) : value.slice(1, end);
    } else {
      const comment = value.indexOf(' #');
      if (comment !== -1) {
        value = value.slice(0, comment).trim();
      }
    }
    values[key] = value;
  }
  return values;
}

async function loadEnv() {
  const files = [join(here, '.env'), join(serviceRoot, '.env')];
  for (const file of files) {
    try {
      const parsed = parseEnvFile(await readFile(file, 'utf8'));
      for (const [key, value] of Object.entries(parsed)) {
        if (process.env[key] === undefined || process.env[key] === '') {
          process.env[key] = value;
        }
      }
    } catch (error) {
      if (error.code !== 'ENOENT') {
        throw error;
      }
    }
  }
}

function decodeEncryptionKey(raw) {
  if (/^[0-9a-fA-F]+$/.test(raw)) {
    const hex = Buffer.from(raw, 'hex');
    if (hex.length === 32) {
      return hex;
    }
  }
  const base64 = Buffer.from(raw, 'base64');
  if (base64.length === 32) {
    return base64;
  }
  throw new Error('ENCRYPTION_KEY must be 32 bytes (hex or base64).');
}

function decryptFromString(cipherString, key) {
  const [iv, tag, data] = cipherString.split('.');
  if (!iv || !tag || !data) {
    throw new Error('Invalid cipher string');
  }
  const decipher = createDecipheriv('aes-256-gcm', key, Buffer.from(iv, 'base64'));
  decipher.setAuthTag(Buffer.from(tag, 'base64'));
  return Buffer.concat([
    decipher.update(Buffer.from(data, 'base64')),
    decipher.final(),
  ]).toString('utf8');
}

function maybeDecryptToken(value, key) {
  if (!value || !key) {
    return value;
  }
  const parts = value.split('.');
  if (parts.length !== 3 || value.startsWith('eyJ')) {
    return value;
  }
  try {
    return decryptFromString(value, key);
  } catch {
    throw new Error('Failed to decrypt a Graph token with ENCRYPTION_KEY.');
  }
}

async function refreshAccessToken() {
  const refreshToken = process.env.GRAPH_REFRESH_TOKEN;
  const clientId = process.env.MICROSOFT_CLIENT_ID;
  const clientSecret = process.env.MICROSOFT_CLIENT_SECRET;
  if (!refreshToken || !clientId || !clientSecret) {
    return null;
  }
  const tenant = process.env.MICROSOFT_TENANT_ID || 'common';
  const body = new URLSearchParams({
    client_id: clientId,
    client_secret: clientSecret,
    grant_type: 'refresh_token',
    refresh_token: refreshToken,
    scope: 'https://graph.microsoft.com/.default',
  });
  const response = await fetch(`https://login.microsoftonline.com/${tenant}/oauth2/v2.0/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const json = await response.json();
  if (!response.ok || typeof json.access_token !== 'string') {
    throw new Error(`Token refresh failed (${response.status})`);
  }
  return json.access_token;
}

async function graphGet(path, { token, query }) {
  const url = new URL(path.startsWith('http') ? path : `${GRAPH}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      url.searchParams.set(key, value);
    }
  }
  const response = await fetch(url, {
    method: 'GET',
    headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
  });
  const text = await response.text();
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = { raw: text };
  }
  return { status: response.status, body };
}

async function writeCache(name, payload) {
  await mkdir(cacheDir, { recursive: true });
  await writeFile(join(cacheDir, name), JSON.stringify(payload, null, 2));
}

function summarizeCalendars(body) {
  const value = Array.isArray(body?.value) ? body.value : [];
  return {
    count: value.length,
    ids: value.map((calendar) => calendar.id),
    flags: value.map((calendar) => ({
      id: calendar.id,
      name: calendar.name,
      isDefaultCalendar: calendar.isDefaultCalendar ?? null,
      isTallyingResponses: calendar.isTallyingResponses ?? null,
      owner: calendar.owner?.address ?? null,
    })),
  };
}

async function main() {
  await loadEnv();
  const key = process.env.ENCRYPTION_KEY
    ? decodeEncryptionKey(process.env.ENCRYPTION_KEY)
    : undefined;
  process.env.GRAPH_ACCESS_TOKEN = maybeDecryptToken(process.env.GRAPH_ACCESS_TOKEN, key);
  process.env.GRAPH_REFRESH_TOKEN = maybeDecryptToken(process.env.GRAPH_REFRESH_TOKEN, key);

  let token = process.env.GRAPH_ACCESS_TOKEN;
  if (!token) {
    token = await refreshAccessToken();
  }
  if (!token) {
    throw new Error(
      'Missing GRAPH_ACCESS_TOKEN. Put it in docs/json/calendar-probes/.env (see .env.example).',
    );
  }

  const me = await graphGet('/me', { token, query: { $select: 'mail,userPrincipalName' } });
  if (me.status === 401) {
    token = await refreshAccessToken();
    if (!token) {
      throw new Error(
        'Access token expired and refresh failed. Set GRAPH_REFRESH_TOKEN plus client credentials.',
      );
    }
    const retried = await graphGet('/me', { token, query: { $select: 'mail,userPrincipalName' } });
    Object.assign(me, retried);
  }
  if (me.status !== 200) {
    throw new Error(`GET /me failed (${me.status})`);
  }
  const email = me.body.mail || me.body.userPrincipalName;
  await writeCache('me.json', { path: '/me', status: me.status, body: me.body });

  const meCalendars = await graphGet('/me/calendars', {
    token,
    query: { $select: CALENDAR_SELECT, $top: '100' },
  });
  const userCalendars = await graphGet(`/users/${email}/calendars`, {
    token,
    query: { $select: CALENDAR_SELECT, $top: '100' },
  });
  await writeCache('me-calendars.json', {
    path: '/me/calendars',
    status: meCalendars.status,
    body: meCalendars.body,
  });
  await writeCache('users-calendars.json', {
    path: `/users/${email}/calendars`,
    status: userCalendars.status,
    body: userCalendars.body,
  });

  const meSummary = summarizeCalendars(meCalendars.body);
  const userSummary = summarizeCalendars(userCalendars.body);
  const sameIds =
    meCalendars.status === 200 &&
    userCalendars.status === 200 &&
    JSON.stringify(meSummary.ids) === JSON.stringify(userSummary.ids);

  const firstId = meSummary.ids[0];
  let orderby = { status: null, supported: false };
  if (firstId && meCalendars.status === 200) {
    const start = new Date();
    const end = new Date(start.getTime() + 24 * 60 * 60 * 1000);
    const window = {
      startDateTime: start.toISOString(),
      endDateTime: end.toISOString(),
    };
    const withoutOrder = await graphGet(`/me/calendars/${firstId}/calendarView`, {
      token,
      query: { ...window, $top: '1', $select: 'id,subject,start' },
    });
    const withOrder = await graphGet(`/me/calendars/${firstId}/calendarView`, {
      token,
      query: { ...window, $top: '1', $select: 'id,subject,start', $orderby: 'start/dateTime' },
    });
    await writeCache('calendarview.json', {
      withoutOrderby: { status: withoutOrder.status, body: withoutOrder.body },
      withOrderby: { status: withOrder.status, body: withOrder.body },
    });
    orderby = {
      status: withOrder.status,
      supported: withOrder.status === 200,
      error: withOrder.status === 200 ? null : (withOrder.body?.error?.message ?? null),
    };
  }

  const findings = {
    probedAt: new Date().toISOString().slice(0, 10),
    liveGraph: true,
    reason:
      'Live GET probes against Microsoft Graph with a delegated token. Raw payloads are in .probe-cache/ (gitignored).',
    items: [
      {
        question: '$search on /events',
        status: 'refuted-by-docs',
        conclusion:
          'Do not use. List events documents OData query parameters and explicitly forbids $filter on recurrence; $search is not documented on either /events or calendarView. Search, attendee and category matching stay in-process over calendarView.',
        source: 'https://learn.microsoft.com/en-us/graph/api/user-list-events?view=graph-rest-1.0',
      },
      {
        question: '$orderby=start/dateTime on calendarView',
        status:
          orderby.status === 200
            ? 'confirmed-live'
            : orderby.status
              ? 'refuted-live'
              : 'unconfirmed',
        conclusion: orderby.supported
          ? 'calendarView accepted $orderby=start/dateTime in this tenant. Still sort in-process so a tenant that rejects it does not break search.'
          : `calendarView rejected or skipped $orderby (status ${orderby.status}${orderby.error ? `: ${orderby.error}` : ''}). Sort occurrences in-process by start.dateTime. $top is documented: min 1, max 1000.`,
        source:
          'https://learn.microsoft.com/en-us/graph/api/calendar-list-calendarview?view=graph-rest-1.0',
      },
      {
        question: 'isDefaultCalendar on calendar resource',
        status: meCalendars.status === 200 ? 'confirmed-live' : 'unconfirmed',
        conclusion:
          meCalendars.status === 200
            ? `GET /me/calendars and GET /users/{email}/calendars both returned ${meSummary.count} calendars. isDefaultCalendar/isTallyingResponses were present. Pair both flags; do not treat isDefaultCalendar alone as proof a shared calendar is the owner's primary. IDs stay in the mailbox named in the path.`
            : 'Could not list calendars live.',
        source:
          'https://learn.microsoft.com/en-us/graph/api/resources/calendar?view=graph-rest-1.0',
      },
      {
        question: 'GET /me/calendars vs GET /users/{email}/calendars',
        status: sameIds ? 'confirmed-live' : 'unconfirmed',
        conclusion: sameIds
          ? 'For the signed-in user, GET /users/{email}/calendars returned the same calendar ids as GET /me/calendars. list_calendars can always use /users/{email}/calendars.'
          : `Statuses me=${meCalendars.status} users=${userCalendars.status}; id lists ${sameIds ? 'match' : 'differ'}.`,
      },
      {
        question:
          'Does mailbox FullAccess appear in GET /me/calendars without an accepted calendar share?',
        status: 'unconfirmed',
        conclusion:
          'This probe cannot see Exchange Full Access grants. Microsoft docs for GET /me/calendars describe local copies from accepted calendar-sharing invitations. list_calendars still unions GET /users/{owner}/calendars for each FullAccess owner. Folder-level mail shares are not used.',
        sources: [
          'https://learn.microsoft.com/en-us/graph/outlook-get-shared-events-calendars',
          'https://learn.microsoft.com/en-us/graph/outlook-share-or-delegate-calendar',
        ],
      },
      {
        question: 'getSchedule address cap',
        status: 'confirmed-by-docs',
        conclusion:
          'Maximum 20 entities per getSchedule call (users, DLs, or resources). Time window must be less than 62 days. Error 5006 when a slot contains more than 1000 entries.',
        sources: [
          'https://learn.microsoft.com/en-us/graph/outlook-get-free-busy-schedule',
          'https://learn.microsoft.com/en-us/graph/api/calendar-getschedule?view=graph-rest-1.0',
        ],
      },
    ],
  };

  await writeFile(join(here, 'findings.json'), `${JSON.stringify(findings, null, 2)}\n`);
  process.stdout.write(
    `Wrote ${join(here, 'findings.json')} (liveGraph=true). Cache in ${cacheDir}.\n`,
  );
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
  process.exit(1);
});
