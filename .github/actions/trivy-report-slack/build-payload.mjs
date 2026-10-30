import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ICON = {
  critical: '🟣',
  high: '🔴',
  medium: '🟠',
  warn: '⚠️',
  shield: '🛡️',
};

const SEVERITIES = ['critical', 'high', 'medium'];
const HEADER_TEXT_LIMIT = 150;
const SECTION_TEXT_LIMIT = 3000;
const CONTEXT_TEXT_LIMIT = 2000;

export const IMAGES_LIMIT = 10;
export const VULNERABILITIES_PER_IMAGE_LIMIT = 5;

function truncate(text, limit) {
  return text.length > limit ? `${text.slice(0, limit - 1)}…` : text;
}

function escapeMrkdwn(text) {
  return String(text).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf-8'));
  } catch {
    return null;
  }
}

function compareVulnerabilities(left, right) {
  return (
    SEVERITIES.indexOf(left.severity) - SEVERITIES.indexOf(right.severity) ||
    left.id.localeCompare(right.id) ||
    left.pkg.localeCompare(right.pkg)
  );
}

function extractVulnerabilities(results) {
  const byKey = new Map();
  for (const result of results.Results ?? []) {
    for (const vulnerability of result.Vulnerabilities ?? []) {
      const severity = vulnerability.Severity?.toLowerCase();
      if (!SEVERITIES.includes(severity)) {
        continue;
      }
      const entry = {
        id: vulnerability.VulnerabilityID,
        pkg: vulnerability.PkgName,
        installed: vulnerability.InstalledVersion,
        fixed: vulnerability.FixedVersion ?? '',
        severity,
      };
      byKey.set(`${entry.id}|${entry.pkg}|${entry.installed}`, entry);
    }
  }
  return [...byKey.values()].sort(compareVulnerabilities);
}

function countSeverities(vulnerabilities) {
  return Object.fromEntries(
    SEVERITIES.map((severity) => [
      severity,
      vulnerabilities.filter((entry) => entry.severity === severity).length,
    ]),
  );
}

function readImage(reportsPath, { service, version }) {
  const directory = path.join(reportsPath, `trivy-registry-${service}`);
  const meta = readJson(path.join(directory, 'meta.json'));
  const results = readJson(path.join(directory, 'trivy-results.json'));
  const image = {
    service,
    version,
    published: true,
    failed: false,
    vulnerabilities: [],
    critical: 0,
    high: 0,
    medium: 0,
  };
  if (meta?.found === false) {
    return { ...image, published: false };
  }
  if (!meta || !results) {
    return { ...image, failed: true };
  }
  const vulnerabilities = extractVulnerabilities(results);
  return { ...image, vulnerabilities, ...countSeverities(vulnerabilities) };
}

function resolveStatus(scanned, failed) {
  if (scanned === 0) {
    return 'empty';
  }
  if (failed === scanned) {
    return 'failed';
  }
  return failed > 0 ? 'partial' : 'success';
}

export function summarize(images) {
  const scanned = images.filter((image) => image.published);
  const failed = scanned.filter((image) => image.failed).length;
  const uniqueSeverities = new Map();
  for (const image of scanned) {
    for (const vulnerability of image.vulnerabilities) {
      uniqueSeverities.set(`${vulnerability.id}|${vulnerability.pkg}`, vulnerability.severity);
    }
  }
  const summed = Object.fromEntries(
    SEVERITIES.map((severity) => [
      severity,
      scanned.reduce((total, image) => total + image[severity], 0),
    ]),
  );
  const unique = countSeverities([...uniqueSeverities.values()].map((severity) => ({ severity })));
  return {
    status: resolveStatus(scanned.length, failed),
    scanned: scanned.length,
    failed,
    ...summed,
    unique,
    images: scanned,
    unpublished: images.filter((image) => !image.published),
  };
}

export function formatSeveritySummary(counts) {
  return SEVERITIES.map((severity) => `${ICON[severity]} ${counts[severity]} ${severity}`).join(
    ' · ',
  );
}

export function buildHeadlineText(summary) {
  const noun = summary.scanned === 1 ? 'image' : 'images';
  return `${formatSeveritySummary(summary.unique)} unique across ${summary.scanned} ${noun}`;
}

export function formatSummedPerImageLine(summary) {
  return `Summed per image: ${formatSeveritySummary(summary)} · ${summary.failed} failed`;
}

export function formatHeaderTitle(title, versionLabel) {
  return `${ICON.shield} ${title} → ${versionLabel}`;
}

export function topOffendingImages(images, limit = IMAGES_LIMIT) {
  return images
    .filter((image) => image.failed || image.vulnerabilities.length > 0)
    .sort((left, right) => {
      const failedDifference = Number(right.failed) - Number(left.failed);
      if (failedDifference !== 0) {
        return failedDifference;
      }
      for (const severity of SEVERITIES) {
        const difference = right[severity] - left[severity];
        if (difference !== 0) {
          return difference;
        }
      }
      return left.service.localeCompare(right.service);
    })
    .slice(0, limit);
}

export function buildMainSectionText(summary) {
  const lines = [];
  if (summary.status === 'empty') {
    lines.push(`${ICON.warn} No published image to scan.`);
  } else if (summary.status === 'failed') {
    lines.push(
      `${ICON.warn} Scan failed for all ${summary.scanned} images. Vulnerability totals are unavailable.`,
    );
  } else {
    if (summary.status === 'partial') {
      lines.push(`${ICON.warn} ${summary.failed} of ${summary.scanned} image(s) failed to scan.`);
    }
    lines.push(buildHeadlineText(summary));
  }
  if (summary.unpublished.length > 0) {
    const names = summary.unpublished
      .map((image) => `${escapeMrkdwn(image.service)}:${escapeMrkdwn(image.version)}`)
      .join(', ');
    lines.push(
      `${ICON.warn} No published image for ${summary.unpublished.length} service(s): ${names}`,
    );
  }
  return lines.join('\n');
}

function rawText(text) {
  return { type: 'raw_text', text };
}

export function buildTopOffendersBlocks(images) {
  const offenders = topOffendingImages(images);
  if (offenders.length === 0) {
    return [];
  }
  const rows = [
    [
      rawText('Service'),
      rawText(`${ICON.critical} Critical`),
      rawText(`${ICON.high} High`),
      rawText(`${ICON.medium} Medium`),
    ],
    ...offenders.map((image) => [
      rawText(`${image.service}:${image.version}${image.failed ? ' (scan failed)' : ''}`),
      rawText(String(image.critical)),
      rawText(String(image.high)),
      rawText(String(image.medium)),
    ]),
  ];
  return [
    {
      type: 'table',
      column_settings: [
        { is_wrapped: true },
        { align: 'right' },
        { align: 'right' },
        { align: 'right' },
      ],
      rows,
    },
  ];
}

export function buildImageDetailText(image) {
  const shown = image.vulnerabilities.slice(0, VULNERABILITIES_PER_IMAGE_LIMIT);
  const hidden = image.vulnerabilities.length - shown.length;
  const lines = [
    `*${escapeMrkdwn(image.service)}:${escapeMrkdwn(image.version)}* ${formatSeveritySummary(image)}`,
    ...shown.map(
      (vulnerability) =>
        `${ICON[vulnerability.severity]} ${vulnerability.severity.toUpperCase()} \`${escapeMrkdwn(vulnerability.id)}\` ${escapeMrkdwn(vulnerability.pkg)} ${escapeMrkdwn(vulnerability.installed)} → ${escapeMrkdwn(vulnerability.fixed || 'no fix')}`,
    ),
  ];
  if (hidden > 0) {
    lines.push(`_${hidden} more not shown_`);
  }
  return lines.join('\n');
}

function buildDetailBlocks(images) {
  const offenders = topOffendingImages(images);
  const omitted = topOffendingImages(images, Number.POSITIVE_INFINITY).length - offenders.length;
  const blocks = offenders
    .filter((image) => image.vulnerabilities.length > 0)
    .map((image) => sectionBlock(buildImageDetailText(image)));
  if (omitted > 0) {
    blocks.push(
      sectionBlock(`_${omitted} more image(s) have findings. Open the run for the full list._`),
    );
  }
  return blocks;
}

function sectionBlock(text) {
  return { type: 'section', text: { type: 'mrkdwn', text: truncate(text, SECTION_TEXT_LIMIT) } };
}

export function buildContextFooterText({
  summary,
  scanLink,
  triggerLabel,
  actor,
  repository,
  workflowName,
}) {
  const parts = [scanLink];
  if (summary.status !== 'failed' && summary.status !== 'empty') {
    parts.push(formatSummedPerImageLine(summary));
  }
  parts.push(
    `Trigger: ${triggerLabel} | By: ${actor} | Repository: ${repository} | Workflow: ${workflowName}`,
  );
  return parts.join(' | ');
}

export function buildPayload(env) {
  const {
    TITLE,
    VERSION_LABEL,
    REPORTS_PATH,
    SERVICES,
    TRIGGER_LABEL,
    REPOSITORY,
    ACTOR,
    WORKFLOW_NAME,
    RUN_URL,
    OTHER_ALERTS = '',
  } = env;
  const expected = JSON.parse(SERVICES);
  assert.ok(Array.isArray(expected), 'SERVICES must be a JSON array');
  assert.ok(RUN_URL, 'RUN_URL is required');

  const summary = summarize(expected.map((entry) => readImage(REPORTS_PATH, entry)));
  const headerTitle = truncate(formatHeaderTitle(TITLE, VERSION_LABEL), HEADER_TEXT_LIMIT);
  const footer = buildContextFooterText({
    summary,
    scanLink: `<${RUN_URL}|Scan Results>`,
    triggerLabel: TRIGGER_LABEL,
    actor: ACTOR,
    repository: REPOSITORY,
    workflowName: WORKFLOW_NAME,
  });

  return {
    text: headerTitle,
    blocks: [
      { type: 'header', text: { type: 'plain_text', text: headerTitle } },
      sectionBlock(buildMainSectionText(summary)),
      ...(OTHER_ALERTS.trim() === '' ? [] : [sectionBlock(OTHER_ALERTS.trim())]),
      ...buildTopOffendersBlocks(summary.images),
      ...buildDetailBlocks(summary.images),
      {
        type: 'context',
        elements: [{ type: 'mrkdwn', text: truncate(footer, CONTEXT_TEXT_LIMIT) }],
      },
    ],
  };
}

const isMainModule =
  process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href;

if (isMainModule) {
  process.stdout.write(JSON.stringify(buildPayload(process.env)));
}
