import assert from 'node:assert';

const MIN_FIX_AGE_DAYS = 3;
const MS_PER_DAY = 86_400_000;
const VERDICT_ORDER = ['block', 'skipped', 'warn'];

export function extractFindings(text) {
  if (typeof text !== 'string' || text.trim() === '') {
    throw new Error('The Trivy report is missing or empty. The gate fails closed.');
  }
  let report;
  try {
    report = JSON.parse(text);
  } catch {
    throw new Error('The Trivy report is not valid JSON. The gate fails closed.');
  }
  if (!Array.isArray(report?.Results)) {
    throw new Error('The Trivy report has no Results section. The gate fails closed.');
  }
  const findings = report.Results.flatMap((result) =>
    (result.Vulnerabilities ?? []).map((vulnerability) => ({
      ...vulnerability,
      resultType: result.Type,
    })),
  );
  const unique = new Map(
    findings.map((finding) => [
      [finding.resultType, finding.PkgName, finding.InstalledVersion, finding.VulnerabilityID].join(
        '|',
      ),
      finding,
    ]),
  );
  return [...unique.values()];
}

function toAgeDays(date, now) {
  const time = Date.parse(date ?? '');
  return Number.isNaN(time) ? null : (now - time) / MS_PER_DAY;
}

function oldestFirst(fixes) {
  return [...fixes].sort((a, b) => (b.ageDays ?? -1) - (a.ageDays ?? -1));
}

async function resolveFix(finding, version, lookup, now) {
  const date = lookup ? await lookup(finding.PkgName, version) : finding.PublishedDate;
  const ageDays = toAgeDays(date, now);
  if (ageDays === null) {
    return { version, source: 'unknown', ageDays: null };
  }
  return { version, source: lookup ? 'registry' : 'advisory', ageDays };
}

async function evaluateFinding(finding, lookups, now) {
  const base = {
    pkg: finding.PkgName,
    installed: finding.InstalledVersion,
    severity: finding.Severity,
    cve: finding.VulnerabilityID,
  };
  const versions = (finding.FixedVersion ?? '')
    .split(',')
    .map((version) => version.trim())
    .filter(Boolean);
  if (versions.length === 0) {
    return {
      ...base,
      fixed: 'none',
      ageDays: null,
      source: 'none',
      verdict: 'warn',
      reason: 'no fix exists',
    };
  }
  const fixes = await Promise.all(
    versions.map((version) => resolveFix(finding, version, lookups[finding.resultType], now)),
  );
  const usable = fixes.filter((fix) => fix.ageDays === null || fix.ageDays >= MIN_FIX_AGE_DAYS);
  const [shown] = oldestFirst(usable.length > 0 ? usable : fixes);
  assert.ok(shown, 'every finding with a fix has at least one resolved fix');
  return {
    ...base,
    fixed: finding.FixedVersion,
    ageDays: shown.ageDays,
    source: shown.source,
    verdict: usable.length > 0 ? 'block' : 'warn',
    reason:
      usable.length > 0
        ? 'a usable fix exists'
        : `every fix is younger than ${MIN_FIX_AGE_DAYS} days`,
  };
}

export function evaluateFindings(findings, { lookups, now }) {
  const cache = new Map();
  const cached = Object.fromEntries(
    Object.entries(lookups).map(([type, lookup]) => [
      type,
      (name, version) => {
        const key = `${type}|${name}|${version}`;
        if (!cache.has(key)) {
          cache.set(key, lookup(name, version));
        }
        return cache.get(key);
      },
    ]),
  );
  return Promise.all(findings.map((finding) => evaluateFinding(finding, cached, now)));
}

export function applyException(rows, { hasLabel }) {
  const blocking = rows.filter((row) => row.verdict === 'block');
  if (blocking.length === 0) {
    return {
      passed: true,
      rows,
      message: hasLabel
        ? 'No finding with a usable fix blocks this release. The label security-exception is not needed.'
        : 'No finding with a usable fix blocks this release.',
    };
  }
  if (!hasLabel) {
    return {
      passed: false,
      rows,
      message: `${blocking.length} finding(s) with a usable fix block this release. To ship anyway, add the label security-exception to this pull request.`,
    };
  }
  return {
    passed: true,
    rows: rows.map((row) => (row.verdict === 'block' ? { ...row, verdict: 'skipped' } : row)),
    message: `The label security-exception is set. ${blocking.length} finding(s) are skipped. The comment on this pull request records who set the label.`,
  };
}

function verdictText(row) {
  if (row.verdict === 'block') {
    return 'BLOCKS';
  }
  return row.verdict === 'skipped' ? 'skipped by exception' : `warning, ${row.reason}`;
}

function ageText(row) {
  return row.source === 'none'
    ? 'n/a'
    : row.ageDays === null
      ? 'unknown'
      : `${row.ageDays.toFixed(1)} days`;
}

function sortRows(rows) {
  return [...rows].sort(
    (a, b) => VERDICT_ORDER.indexOf(a.verdict) - VERDICT_ORDER.indexOf(b.verdict),
  );
}

const escapeCell = (value) => String(value).replaceAll('|', '\\|');

const escapeAnnotation = (value) =>
  value.replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A');

export function renderSummary(rows, message) {
  const header = [
    '## Release gate',
    '',
    message,
    '',
    '| Package | Installed | Fixed | Severity | CVE | Fix age | Age source | Verdict |',
    '| --- | --- | --- | --- | --- | --- | --- | --- |',
  ];
  const lines = sortRows(rows).map(
    (row) =>
      `| ${[row.pkg, row.installed, row.fixed, row.severity, row.cve, ageText(row), row.source, verdictText(row)].map(escapeCell).join(' | ')} |`,
  );
  return [...header, ...lines, ''].join('\n');
}

export function renderAnnotations(rows) {
  return sortRows(rows).map((row) => {
    const level = row.verdict === 'block' ? 'error' : 'warning';
    const text = `${row.pkg} ${row.installed} fixed in ${row.fixed} (${row.severity}, ${row.cve}): ${verdictText(row)}`;
    return `::${level}::${escapeAnnotation(text)}`;
  });
}

export async function runGate({ reportText, hasLabel, lookups, now }) {
  const findings = extractFindings(reportText);
  const rows = await evaluateFindings(findings, { lookups, now });
  const outcome = applyException(rows, { hasLabel });
  return {
    passed: outcome.passed,
    message: outcome.message,
    summary: renderSummary(outcome.rows, outcome.message),
    annotations: renderAnnotations(outcome.rows),
  };
}
