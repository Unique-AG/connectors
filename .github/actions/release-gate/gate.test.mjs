import assert from 'node:assert/strict';
import test from 'node:test';
import { extractFindings, runGate } from './gate.mjs';

const NOW = Date.parse('2026-10-27T12:00:00Z');
const daysAgo = (days) => new Date(NOW - days * 86_400_000).toISOString();

const vulnerability = (overrides = {}) => ({
  PkgName: 'urllib3',
  InstalledVersion: '1.26.0',
  FixedVersion: '1.26.19',
  Severity: 'HIGH',
  VulnerabilityID: 'CVE-2026-0001',
  PublishedDate: daysAgo(30),
  ...overrides,
});

const report = (vulnerabilities, type = 'python-pkg') =>
  JSON.stringify({ Results: [{ Type: type, Vulnerabilities: vulnerabilities }] });

const registry = (dates) => async (name, version) => dates[`${name}@${version}`] ?? null;

const gate = (overrides) =>
  runGate({
    reportText: report([vulnerability()]),
    hasLabel: false,
    comments: [],
    lookups: { 'python-pkg': registry({}), 'node-pkg': registry({}) },
    now: NOW,
    ...overrides,
  });

test('takes the fix age from the registry publish date', async () => {
  const result = await gate({
    lookups: { 'python-pkg': registry({ 'urllib3@1.26.19': daysAgo(10) }) },
  });
  assert.equal(result.passed, false);
  assert.match(
    result.summary,
    /\| urllib3 \| 1\.26\.0 \| 1\.26\.19 \| HIGH \| CVE-2026-0001 \| 10\.0 days \| registry \| BLOCKS \|/,
  );
});

test('takes the fix age from the npm registry for node packages', async () => {
  const result = await gate({
    reportText: report([vulnerability({ PkgName: 'tar', FixedVersion: '7.5.0' })], 'node-pkg'),
    lookups: { 'node-pkg': registry({ 'tar@7.5.0': daysAgo(1) }) },
  });
  assert.equal(result.passed, true);
  assert.match(
    result.summary,
    /1\.0 days \| registry \| warning, every fix is younger than 3 days/,
  );
});

test('falls back to the advisory date when the registry has no date', async () => {
  const result = await gate({});
  assert.equal(result.passed, false);
  assert.match(result.summary, /30\.0 days \| advisory \| BLOCKS/);
});

test('uses the advisory date for results without a registry lookup', async () => {
  const result = await gate({
    reportText: report([vulnerability({ PublishedDate: daysAgo(1) })], 'debian'),
  });
  assert.equal(result.passed, true);
  assert.match(result.summary, /advisory \| warning/);
});

test('blocks when the age is unknown', async () => {
  const result = await gate({
    reportText: report([vulnerability({ PublishedDate: undefined })]),
  });
  assert.equal(result.passed, false);
  assert.match(result.summary, /unknown \| unknown \| BLOCKS/);
  assert.match(result.annotations[0], /^::error::/);
});

test('blocks when any listed fix is old enough', async () => {
  const result = await gate({
    reportText: report([vulnerability({ FixedVersion: '2.4.0, 1.20.9' })]),
    lookups: {
      'python-pkg': registry({ 'urllib3@2.4.0': daysAgo(1), 'urllib3@1.20.9': daysAgo(8) }),
    },
  });
  assert.equal(result.passed, false);
  assert.match(result.summary, /8\.0 days \| registry \| BLOCKS/);
});

test('blocks when one listed fix has an unknown age', async () => {
  const result = await gate({
    reportText: report([
      vulnerability({ FixedVersion: '2.4.0, 1.20.9', PublishedDate: undefined }),
    ]),
    lookups: { 'python-pkg': registry({ 'urllib3@2.4.0': daysAgo(1) }) },
  });
  assert.equal(result.passed, false);
});

test('passes with a warning when every listed fix is young', async () => {
  const result = await gate({
    reportText: report([vulnerability({ FixedVersion: '2.4.0, 1.20.9' })]),
    lookups: {
      'python-pkg': registry({ 'urllib3@2.4.0': daysAgo(1), 'urllib3@1.20.9': daysAgo(2) }),
    },
  });
  assert.equal(result.passed, true);
  assert.match(result.annotations[0], /^::warning::/);
});

test('passes with a warning when no fix exists', async () => {
  const result = await gate({ reportText: report([vulnerability({ FixedVersion: undefined })]) });
  assert.equal(result.passed, true);
  assert.match(
    result.summary,
    /\| none \| HIGH \| CVE-2026-0001 \| n\/a \| none \| warning, no fix exists/,
  );
});

test('fails when the label is set without a stamp', async () => {
  const result = await gate({ hasLabel: true, comments: ['looks fine'] });
  assert.equal(result.passed, false);
  assert.match(result.message, /no comment starts with "Security exception approved by:"/);
});

test('passes when the label and a stamp exist and lists the skipped findings', async () => {
  const result = await gate({
    hasLabel: true,
    comments: ['hello', 'Security exception approved by: @alice for UN-1'],
  });
  assert.equal(result.passed, true);
  assert.match(result.summary, /CVE-2026-0001 \| 30\.0 days \| advisory \| skipped by exception/);
  assert.match(result.annotations[0], /^::warning::/);
});

test('ignores a stamp when the label is not set', async () => {
  const result = await gate({ comments: ['Security exception approved by: @alice'] });
  assert.equal(result.passed, false);
});

test('fails closed when the Trivy report is missing or has no results', async () => {
  for (const reportText of [null, '', 'not json', '{}', '{"Results": null}']) {
    await assert.rejects(gate({ reportText }), /fails closed/);
  }
});

test('passes when the report holds results without findings', async () => {
  const result = await gate({ reportText: JSON.stringify({ Results: [{ Type: 'debian' }] }) });
  assert.equal(result.passed, true);
});

test('removes duplicate findings across results', () => {
  const text = JSON.stringify({
    Results: [
      { Type: 'python-pkg', Vulnerabilities: [vulnerability()] },
      { Type: 'python-pkg', Vulnerabilities: [vulnerability()] },
    ],
  });
  assert.equal(extractFindings(text).length, 1);
});

test('looks up each package version once', async () => {
  let calls = 0;
  await gate({
    reportText: report([vulnerability(), vulnerability({ VulnerabilityID: 'CVE-2026-0002' })]),
    lookups: {
      'python-pkg': async () => {
        calls += 1;
        return daysAgo(10);
      },
    },
  });
  assert.equal(calls, 1);
});
