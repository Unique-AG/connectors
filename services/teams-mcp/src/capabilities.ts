import assert from 'node:assert';

/**
 * Single source of truth for reading the two independent capability toggles from
 * the environment. These read `process.env` directly (rather than the Nest config
 * service) to match the import-time module-gating pattern used in
 * `kb-integration.module.ts` and `chat.module.ts`, so gating and the startup
 * assertion stay consistent.
 */

/**
 * Chat capability (Teams chat/channel messaging tools). Defaults to enabled for
 * backward compatibility — only an explicit `CHAT_INTEGRATION=disabled` turns it off.
 */
export function isChatEnabled(): boolean {
  return process.env.CHAT_INTEGRATION !== 'disabled';
}

/**
 * Ingestion capability (Unique knowledge-base transcript/recording ingestion).
 * Enabled only when `UNIQUE_INTEGRATION=enabled`, mirroring the existing behaviour.
 */
export function isIngestionEnabled(): boolean {
  return process.env.UNIQUE_INTEGRATION === 'enabled';
}

/**
 * At least one capability must be enabled for the server to do anything useful.
 * A both-disabled configuration is a misconfiguration and fails fast at startup.
 */
export function assertAtLeastOneCapabilityEnabled(): void {
  assert.ok(
    isChatEnabled() || isIngestionEnabled(),
    'At least one capability must be enabled: set CHAT_INTEGRATION=enabled (default) ' +
      'and/or UNIQUE_INTEGRATION=enabled. Both are currently disabled, so the server ' +
      'would expose no tools.',
  );
}
