/**
 * Get a Microsoft access token via local redirect (auth code flow).
 * Reads CLIENT_ID + CLIENT_SECRET from .env automatically.
 *
 * Usage:
 *   npx tsx scripts/get-token.ts
 */

import { readFileSync } from 'node:fs';
import { createServer } from 'node:http';
import { resolve } from 'node:path';

function loadEnv() {
  const envPath = resolve(__dirname, '../.env');
  for (const line of readFileSync(envPath, 'utf-8').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const idx = trimmed.indexOf('=');
    if (idx === -1) continue;
    const key = trimmed.slice(0, idx).trim();
    const value = trimmed.slice(idx + 1).split('#')[0].trim();
    process.env[key] ??= value;
  }
}

loadEnv();

const CLIENT_ID = process.env.MICROSOFT_CLIENT_ID;
const CLIENT_SECRET = process.env.MICROSOFT_CLIENT_SECRET;
if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error('MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET not found in .env');
  process.exit(1);
}

const PORT = 9542;
const REDIRECT_URI = `http://localhost:${PORT}/auth/callback`;
const TENANT = 'common';
const SCOPES = [
  'openid',
  'profile',
  'email',
  'offline_access',
  'User.Read',
  'OnlineMeetings.Read',
  'OnlineMeetingRecording.Read.All',
  'OnlineMeetingTranscript.Read.All',
  'ChannelMessage.Send',
  'ChatMessage.Send',
  'Chat.ReadBasic',
  'Chat.Read',
  'Team.ReadBasic.All',
  'Channel.ReadBasic.All',
  'ChannelMessage.Read.All',
].join(' ');

async function exchangeCode(code: string): Promise<string> {
  const res = await fetch(`https://login.microsoftonline.com/${TENANT}/oauth2/v2.0/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      client_id: CLIENT_ID,
      client_secret: CLIENT_SECRET,
      grant_type: 'authorization_code',
      code,
      redirect_uri: REDIRECT_URI,
      scope: SCOPES,
    }).toString(),
  });
  const data = (await res.json()) as Record<string, string>;
  if (data.error) throw new Error(`${data.error}: ${data.error_description}`);
  return data.access_token;
}

async function main() {
  const authUrl =
    `https://login.microsoftonline.com/${TENANT}/oauth2/v2.0/authorize` +
    `?client_id=${CLIENT_ID}` +
    `&response_type=code` +
    `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}` +
    `&scope=${encodeURIComponent(SCOPES)}` +
    `&response_mode=query`;

  const token = await new Promise<string>((resolve, reject) => {
    const server = createServer(async (req, res) => {
      const url = new URL(req.url ?? '/', `http://localhost:${PORT}`);
      if (url.pathname !== '/auth/callback') return;

      const code = url.searchParams.get('code');
      const error = url.searchParams.get('error');

      if (error) {
        res.writeHead(400);
        res.end('Auth error. Check the terminal for details.');
        server.close();
        return reject(new Error(error));
      }

      if (!code) {
        res.writeHead(400);
        res.end('No code received');
        server.close();
        return reject(new Error('No code in callback'));
      }

      try {
        const token = await exchangeCode(code);
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end('<h2>✓ Token acquired! You can close this tab.</h2>');
        server.close();
        resolve(token);
      } catch (err) {
        res.writeHead(500);
        res.end('Token exchange failed. Check the terminal for details.');
        server.close();
        reject(err);
      }
    });

    server.listen(PORT, () => {
      console.log(`\nOpening browser for Microsoft login...`);
      console.log(`If it doesn't open, visit:\n${authUrl}\n`);
      // open browser
      const { execSync } = require('node:child_process');
      try {
        execSync(`open "${authUrl}"`);
      } catch {
        // non-mac fallback
        try { execSync(`xdg-open "${authUrl}"`); } catch { /* ignore */ }
      }
    });

    server.on('error', reject);
  });

  console.log('✓ Token acquired!\n');
  console.log('ACCESS_TOKEN=' + token);
  console.log('\nRun the verify script:');
  console.log(`ACCESS_TOKEN='${token}' npx tsx scripts/verify-get-all-transcripts.ts`);
}

main().catch((err) => {
  console.error('Failed:', err.message);
  process.exit(1);
});
