import assert from 'node:assert/strict';
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import {
  buildHeadlineText,
  buildMainSectionText,
  buildPayload,
  buildRepositoryBlocks,
  buildRepositoryHeadlineText,
  buildTopOffendersBlocks,
  formatHeaderTitle,
  formatSeveritySummary,
  formatSummedPerImageLine,
  summarize,
  topOffendingImages,
} from './build-payload.mjs';

const vulnerability = (id, severity, pkg = 'openssl') => ({
  id,
  pkg,
  installed: '3.0.1',
  fixed: '3.0.2',
  severity,
});

const image = (service, vulnerabilities = [], overrides = {}) => ({
  service,
  version: '1.2.3',
  published: true,
  failed: false,
  vulnerabilities,
  critical: vulnerabilities.filter((entry) => entry.severity === 'critical').length,
  high: vulnerabilities.filter((entry) => entry.severity === 'high').length,
  medium: vulnerabilities.filter((entry) => entry.severity === 'medium').length,
  ...overrides,
});

const trivyVulnerability = (id, severity, pkg = 'openssl') => ({
  VulnerabilityID: id,
  PkgName: pkg,
  InstalledVersion: '3.0.1',
  FixedVersion: '3.0.2',
  Severity: severity,
});

function writeReport(root, service, { meta, results }) {
  const directory = join(root, `trivy-registry-${service}`);
  mkdirSync(directory, { recursive: true });
  if (meta) {
    writeFileSync(join(directory, 'meta.json'), JSON.stringify(meta));
  }
  if (results) {
    writeFileSync(join(directory, 'trivy-results.json'), JSON.stringify(results));
  }
}

function withReports(setup, run) {
  const root = mkdtempSync(join(tmpdir(), 'trivy-report-'));
  try {
    setup(root);
    return run(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

const baseEnv = {
  CHANNEL: 'C0C1PR9CNMP',
  TITLE: 'Security Trivy Scan (Registry)',
  VERSION_LABEL: 'published-images',
  TRIGGER_LABEL: 'scheduled',
  REPOSITORY: 'Unique-AG/connectors',
  ACTOR: 'github-actions[bot]',
  WORKFLOW_NAME: '[Security] Trivy Nightly Scan',
  RUN_URL: 'https://github.com/Unique-AG/connectors/actions/runs/1',
};

test('formatHeaderTitle joins the title and the label', () => {
  assert.equal(
    formatHeaderTitle('Security Trivy Scan (Registry)', 'published-images'),
    '🛡️ Security Trivy Scan (Registry) → published-images',
  );
});

test('formatSeveritySummary lists critical, high, and medium counts', () => {
  assert.equal(
    formatSeveritySummary({ critical: 0, high: 4, medium: 0 }),
    '🟣 0 critical · 🔴 4 high · 🟠 0 medium',
  );
});

test('summarize sums per image and counts unique findings once', () => {
  const summary = summarize([
    image('admin', [vulnerability('CVE-1', 'critical'), vulnerability('CVE-2', 'medium')]),
    image('chat', [vulnerability('CVE-1', 'critical'), vulnerability('CVE-3', 'high')]),
    image('old', [], { published: false }),
  ]);

  assert.equal(summary.status, 'success');
  assert.equal(summary.scanned, 2);
  assert.deepEqual([summary.critical, summary.high, summary.medium], [2, 1, 1]);
  assert.deepEqual(summary.unique, { critical: 1, high: 1, medium: 1 });
  assert.deepEqual(
    summary.unpublished.map((entry) => entry.service),
    ['old'],
  );
});

test('summarize reports partial, failed, and empty statuses', () => {
  assert.equal(summarize([image('a'), image('b', [], { failed: true })]).status, 'partial');
  assert.equal(summarize([image('a', [], { failed: true })]).status, 'failed');
  assert.equal(summarize([image('a', [], { published: false })]).status, 'empty');
});

test('buildHeadlineText uses the unique counts', () => {
  assert.equal(
    buildHeadlineText({ scanned: 32, unique: { critical: 1, high: 8, medium: 27 } }),
    '🟣 1 critical · 🔴 8 high · 🟠 27 medium unique across 32 images',
  );
});

test('buildHeadlineText ends with a check mark when no critical and no high finding is left', () => {
  const unique = { critical: 0, high: 0, medium: 27 };

  assert.equal(
    buildHeadlineText({ status: 'success', scanned: 3, unique }),
    '🟣 0 critical · 🔴 0 high · 🟠 27 medium unique across 3 images ✅',
  );
  assert.equal(buildHeadlineText({ status: 'partial', scanned: 3, unique }).endsWith('✅'), false);
  assert.equal(
    buildHeadlineText({ status: 'success', scanned: 3, unique: { ...unique, high: 1 } }).endsWith(
      '✅',
    ),
    false,
  );
});

test('buildHeadlineText uses the singular for one image', () => {
  assert.match(
    buildHeadlineText({ scanned: 1, unique: { critical: 0, high: 0, medium: 0 } }),
    /across 1 image$/,
  );
});

test('formatSummedPerImageLine includes the failed count', () => {
  assert.equal(
    formatSummedPerImageLine({ critical: 2, high: 130, medium: 157, failed: 0 }),
    'Summed per image: 🟣 2 critical · 🔴 130 high · 🟠 157 medium · 0 failed',
  );
});

test('buildMainSectionText warns about unpublished services with their tags', () => {
  const text = buildMainSectionText(
    summarize([image('admin'), image('old-svc', [], { published: false, version: '0.1.0' })]),
  );

  assert.match(text, /unique across 1 image/);
  assert.match(text, /No published image for 1 service\(s\): old-svc:0\.1\.0/);
});

test('buildMainSectionText keeps the headline when some scans fail', () => {
  const text = buildMainSectionText(summarize([image('a'), image('b', [], { failed: true })]));

  assert.match(text, /1 of 2 image\(s\) failed to scan/);
  assert.match(text, /unique across 2 images/);
});

test('buildMainSectionText hides the totals when every scan fails', () => {
  const text = buildMainSectionText(summarize([image('a', [], { failed: true })]));

  assert.match(text, /Vulnerability totals are unavailable/);
  assert.equal(text.includes('0 critical'), false);
});

test('buildMainSectionText says so when nothing is published', () => {
  const text = buildMainSectionText(summarize([image('a', [], { published: false })]));

  assert.match(text, /No published image to scan/);
});

test('topOffendingImages puts failed scans first, then sorts by severity and name', () => {
  const ranked = topOffendingImages([
    image('gatekeeper', [vulnerability('A', 'critical'), vulnerability('B', 'high')]),
    image('admin', [vulnerability('A', 'critical'), vulnerability('C', 'high')]),
    image('worker', [vulnerability('A', 'critical'), vulnerability('B', 'critical')]),
    image('chat', [vulnerability('A', 'high')]),
    image('broken', [], { failed: true }),
    image('clean'),
  ]);

  assert.deepEqual(
    ranked.map((entry) => entry.service),
    ['broken', 'worker', 'admin', 'gatekeeper', 'chat'],
  );
});

test('topOffendingImages does not change the input order', () => {
  const images = [
    image('b', [vulnerability('A', 'high')]),
    image('a', [vulnerability('A', 'critical')]),
  ];
  topOffendingImages(images);

  assert.deepEqual(
    images.map((entry) => entry.service),
    ['b', 'a'],
  );
});

test('buildTopOffendersBlocks lists every image with findings, with its tag', () => {
  const images = Array.from({ length: 13 }, (_, index) =>
    image(`service-${String(index).padStart(2, '0')}`, [vulnerability(`CVE-${index}`, 'high')]),
  );
  const [table] = buildTopOffendersBlocks(images);

  assert.equal(table.type, 'table');
  assert.equal(table.rows.length, 14);
  assert.deepEqual(
    table.rows[0].map((cell) => cell.text),
    ['Service', '🟣 Critical', '🔴 High', '🟠 Medium'],
  );
  assert.deepEqual(
    table.rows[1].map((cell) => cell.text),
    ['service-00:1.2.3', '0', '1', '0'],
  );
});

test('buildTopOffendersBlocks marks failed scans in the service column', () => {
  const [table] = buildTopOffendersBlocks([image('gatekeeper', [], { failed: true })]);

  assert.equal(table.rows[1][0].text, 'gatekeeper:1.2.3 (scan failed)');
});

test('buildTopOffendersBlocks returns no table for clean images', () => {
  assert.deepEqual(buildTopOffendersBlocks([image('admin')]), []);
});

test('buildPayload reads the reports and builds header, table, repository section, and footer', () => {
  const payload = withReports(
    (root) => {
      writeReport(root, 'admin', {
        meta: { service: 'admin', version: '1.2.3', found: true },
        results: {
          Results: [
            {
              Vulnerabilities: [
                trivyVulnerability('CVE-1', 'CRITICAL'),
                trivyVulnerability('CVE-2', 'MEDIUM', 'zlib'),
                trivyVulnerability('CVE-3', 'LOW'),
              ],
            },
          ],
        },
      });
      writeReport(root, 'chat', {
        meta: { service: 'chat', version: '1.2.3', found: true },
        results: { Results: [] },
      });
      writeReport(root, 'old', { meta: { service: 'old', version: '0.1.0', found: false } });
    },
    (root) =>
      buildPayload({
        ...baseEnv,
        REPOSITORY_ALERTS: JSON.stringify({ lockfiles: noAlerts, config: noAlerts }),
        REPORTS_PATH: root,
        SERVICES: JSON.stringify([
          { service: 'admin', version: '1.2.3' },
          { service: 'chat', version: '1.2.3' },
          { service: 'old', version: '0.1.0' },
        ]),
      }),
  );
  const types = payload.blocks.map((block) => block.type);

  assert.equal(payload.text, '🛡️ Security Trivy Scan (Registry) → published-images');
  assert.deepEqual(types, ['header', 'section', 'table', 'section', 'context']);
  assert.match(
    payload.blocks[1].text.text,
    /🟣 1 critical · 🔴 0 high · 🟠 1 medium unique across 2 images/,
  );
  assert.match(payload.blocks[1].text.text, /No published image for 1 service\(s\): old:0\.1\.0/);
  assert.deepEqual(
    payload.blocks[2].rows[1].map((cell) => cell.text),
    ['admin:1.2.3', '1', '0', '1'],
  );
  const footer = payload.blocks.at(-1).elements[0].text;
  assert.equal(
    footer.startsWith(
      '<https://github.com/Unique-AG/connectors/actions/runs/1|Scan Results> | Summed per image',
    ),
    true,
  );
  assert.match(
    footer,
    /Trigger: scheduled \| By: github-actions\[bot\] \| Repository: Unique-AG\/connectors \| Workflow: /,
  );
});

test('buildPayload marks a service without an artifact as a failed scan', () => {
  const payload = withReports(
    () => {},
    (root) =>
      buildPayload({
        ...baseEnv,
        REPORTS_PATH: root,
        SERVICES: JSON.stringify([{ service: 'admin', version: '1.2.3' }]),
      }),
  );

  assert.match(payload.blocks[1].text.text, /Scan failed for all 1 images/);
  assert.equal(
    payload.blocks.some((block) => block.type === 'table'),
    true,
  );
  assert.equal(payload.blocks.at(-1).elements[0].text.includes('Summed per image'), false);
});

test('buildPayload keeps every text within the Slack limits', () => {
  const longName = 'x'.repeat(500);
  const payload = withReports(
    (root) => {
      writeReport(root, 'admin', {
        meta: { found: true },
        results: {
          Results: [
            {
              Vulnerabilities: Array.from({ length: 200 }, (_, index) =>
                trivyVulnerability(`CVE-${index}`, 'HIGH', longName),
              ),
            },
          ],
        },
      });
    },
    (root) =>
      buildPayload({
        ...baseEnv,
        TITLE: longName,
        REPORTS_PATH: root,
        SERVICES: JSON.stringify([
          { service: 'admin', version: '1.2.3' },
          ...Array.from({ length: 40 }, (_, index) => ({
            service: `gone-${longName}-${index}`,
            version: '0.0.1',
          })),
        ]),
      }),
  );

  assert.equal(payload.blocks[0].text.text.length <= 150, true);
  for (const block of payload.blocks.filter((entry) => entry.type === 'section')) {
    assert.equal(block.text.text.length <= 3000, true);
  }
  assert.equal(payload.blocks.length <= 50, true);
});

test('buildPayload rejects a SERVICES value that is not an array', () => {
  assert.throws(
    () => buildPayload({ ...baseEnv, REPORTS_PATH: '.', SERVICES: '{}' }),
    /SERVICES must be a JSON array/,
  );
});

const repositoryAlerts = (lockfiles, config) => ({ lockfiles, config });
const noAlerts = { critical: 0, high: 0, medium: 0 };

test('buildRepositoryHeadlineText sums both scans and ends with a check mark when no critical and no high is left', () => {
  assert.equal(
    buildRepositoryHeadlineText(
      repositoryAlerts({ critical: 0, high: 0, medium: 5 }, { critical: 0, high: 0, medium: 1 }),
    ),
    '🟣 0 critical · 🔴 0 high · 🟠 6 medium across 2 scans ✅',
  );
  assert.equal(
    buildRepositoryHeadlineText(
      repositoryAlerts({ critical: 1, high: 2, medium: 3 }, { critical: 0, high: 1, medium: 0 }),
    ),
    '🟣 1 critical · 🔴 3 high · 🟠 3 medium across 2 scans',
  );
});

test('buildRepositoryBlocks always has the title and the headline, and a row only for a scan with findings', () => {
  const [section, table] = buildRepositoryBlocks(
    repositoryAlerts({ critical: 0, high: 0, medium: 5 }, noAlerts),
  );

  assert.equal(
    section.text.text,
    '*Repository (main)*\n🟣 0 critical · 🔴 0 high · 🟠 5 medium across 2 scans ✅',
  );
  assert.deepEqual(
    table.rows.map((row) => row.map((cell) => cell.text)),
    [
      ['Scan', '🟣 Critical', '🔴 High', '🟠 Medium'],
      ['📦 Lock files', '0', '0', '5'],
    ],
  );
});

test('buildRepositoryBlocks has no table when both scans are clean', () => {
  const blocks = buildRepositoryBlocks(repositoryAlerts(noAlerts, noAlerts));

  assert.equal(blocks.length, 1);
  assert.match(blocks[0].text.text, /0 critical · 🔴 0 high · 🟠 0 medium across 2 scans ✅$/);
});

test('buildRepositoryBlocks says so when the alerts could not be read', () => {
  const blocks = buildRepositoryBlocks(null);

  assert.equal(blocks.length, 1);
  assert.match(blocks[0].text.text, /The open alerts could not be read\.$/);
});

test('buildPayload sets the channel for a legacy webhook', () => {
  const { channel } = buildPayload({ ...baseEnv, REPORTS_PATH: '.', SERVICES: '[]' });
  assert.equal(channel, 'C0C1PR9CNMP');
});

test('buildPayload rejects a missing CHANNEL', () => {
  assert.throws(
    () => buildPayload({ ...baseEnv, CHANNEL: '', REPORTS_PATH: '.', SERVICES: '[]' }),
    /CHANNEL is required/,
  );
});
