/**
 * Verify that getAllTranscripts works without knowing meeting IDs.
 *
 * Usage:
 *   ACCESS_TOKEN=<your_token> npx tsx scripts/verify-get-all-transcripts.ts
 *
 * Or with optional filters:
 *   ACCESS_TOKEN=<token> START_DATE=2024-01-01 npx tsx scripts/verify-get-all-transcripts.ts
 *
 * To get an access token manually:
 *   1. Go to https://developer.microsoft.com/en-us/graph/graph-explorer
 *   2. Sign in and consent to OnlineMeetingTranscript.Read.All
 *   3. Copy the access token from the "Access token" tab
 */

const BASE_URL = 'https://graph.microsoft.com/v1.0';

const token = process.env.ACCESS_TOKEN;
if (!token) {
  console.error('ERROR: ACCESS_TOKEN env var is required');
  process.exit(1);
}

const startDate = process.env.START_DATE ?? new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

async function graphGet(url: string) {
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Graph API error ${res.status}: ${body}`);
  }
  return res.json() as Promise<Record<string, unknown>>;
}

async function getCurrentUser() {
  const me = await graphGet(`${BASE_URL}/me?$select=id,displayName,mail`);
  return me as { id: string; displayName: string; mail: string };
}

async function getAllTranscripts(userId: string) {
  const transcripts: unknown[] = [];

  // Note: /delta requires application permissions (not supported in delegated context).
  // getAllTranscripts without /delta works with delegated permissions.
  let nextLink: string | undefined =
    `${BASE_URL}/users/${userId}/onlineMeetings/getAllTranscripts` +
    `(meetingOrganizerUserId='${userId}',startDateTime=${startDate})`;

  let page = 0;
  while (nextLink) {
    page++;
    console.log(`  Fetching page ${page}...`);
    const data = await graphGet(nextLink);
    const items = (data.value as unknown[]) ?? [];
    transcripts.push(...items);
    nextLink = data['@odata.nextLink'] as string | undefined;
  }

  return transcripts;
}

async function main() {
  console.log('=== Verify getAllTranscripts (no meeting IDs needed) ===\n');

  console.log('1. Resolving current user...');
  const me = await getCurrentUser();
  console.log(`   User: ${me.displayName} (${me.mail})`);
  console.log(`   ID:   ${me.id}`);

  console.log(`\n2. Fetching all transcripts since ${startDate}...`);
  const transcripts = await getAllTranscripts(me.id);

  console.log(`\n3. Results: ${transcripts.length} transcript(s) found\n`);

  for (const t of transcripts) {
    const transcript = t as {
      id: string;
      meetingId: string;
      createdDateTime: string;
      transcriptContentUrl: string;
      meetingOrganizer?: { user?: { id: string } };
    };
    console.log('---');
    console.log(`  Transcript ID:   ${transcript.id}`);
    console.log(`  Meeting ID:      ${transcript.meetingId}`);
    console.log(`  Created:         ${transcript.createdDateTime}`);
    console.log(`  Content URL:     ${transcript.transcriptContentUrl}`);
    console.log(`  Organizer ID:    ${transcript.meetingOrganizer?.user?.id ?? 'n/a'}`);
  }

  if (transcripts.length === 0) {
    console.log('  No transcripts found. Try extending START_DATE further back.');
    console.log('  Example: START_DATE=2023-01-01T00:00:00Z');
  }
}

main().catch((err) => {
  console.error('\nFailed:', err.message);
  process.exit(1);
});
