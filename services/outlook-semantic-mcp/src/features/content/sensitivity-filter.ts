import { Inject, Injectable } from '@nestjs/common';
import * as z from 'zod';
import { type FeaturesConfig, featuresConfig, LegacySensitivity } from '~/config';

export enum SensitivityVerdict {
  Allowed = 'allowed',
  Excluded = 'excluded',
  // The properties are missing or malformed, so the message is treated as excluded.
  Unreadable = 'unreadable',
}

export type SensitivityJudgement =
  | { verdict: SensitivityVerdict.Allowed }
  // `label` is the configured entry that matched, never text from the message, which its sender
  // controls. An entry configured by id says nothing about the label's name.
  | { verdict: SensitivityVerdict.Excluded; label: string; configuredById: boolean }
  | { verdict: SensitivityVerdict.Unreadable };

const ALLOWED: SensitivityJudgement = { verdict: SensitivityVerdict.Allowed };
const UNREADABLE: SensitivityJudgement = { verdict: SensitivityVerdict.Unreadable };

// Mail is filtered on these properties after Graph returns it; see
// testing-utils/sensitivity-label-probe for how Graph exposes them.
@Injectable()
export class SensitivityFilter {
  public readonly isActive: boolean;
  public readonly expand =
    `singleValueExtendedProperties($filter=id eq '${PURVIEW_LABELS_PROPERTY}' or id eq '${LEGACY_SENSITIVITY_PROPERTY}')`;
  // Lower-cased entry → the entry as configured.
  private readonly excludedLabels: ReadonlyMap<string, string>;
  private readonly excludedLegacy: ReadonlySet<LegacySensitivity>;
  private readonly excludesLabelNames: boolean;

  public constructor(@Inject(featuresConfig.KEY) features: FeaturesConfig) {
    this.excludedLabels = new Map(
      [...features.sensitivityExclusions.labels].map((label) => [label.toLowerCase(), label]),
    );
    this.excludedLegacy = features.sensitivityExclusions.legacy;
    this.isActive = this.excludedLabels.size > 0 || this.excludedLegacy.size > 0;
    this.excludesLabelNames = [...this.excludedLabels.keys()].some(
      (label) => !GUID_PATTERN.test(label),
    );
  }

  // Takes the message's `singleValueExtendedProperties` as Graph sent them, so one malformed
  // message is judged unreadable instead of failing the page it is on.
  public judge(rawProperties: unknown): SensitivityJudgement {
    if (!this.isActive) {
      return ALLOWED;
    }
    const parsed = extendedPropertiesSchema.safeParse(rawProperties);
    if (!parsed.success) {
      return UNREADABLE;
    }
    const values = new Map(parsed.data.map(({ id, value }) => [canonicalPropertyId(id), value]));
    // Other property ids mean Graph ignored the $expand filter. Every message carries the legacy
    // flag, 0 when unset.
    const legacyValue = values.get(canonicalPropertyId(LEGACY_SENSITIVITY_PROPERTY));
    const legacy = typeof legacyValue === 'string' ? LEGACY_VALUES.get(legacyValue) : undefined;
    if ([...values.keys()].some((id) => !KNOWN_PROPERTIES.has(id)) || legacy === undefined) {
      return UNREADABLE;
    }
    if (legacy !== null && this.excludedLegacy.has(legacy)) {
      return {
        verdict: SensitivityVerdict.Excluded,
        label: LEGACY_DISPLAY_NAMES[legacy],
        configuredById: false,
      };
    }

    // Absent or empty means no label; present without a value cannot be read.
    const purviewKey = canonicalPropertyId(PURVIEW_LABELS_PROPERTY);
    const purviewValue = values.has(purviewKey) ? values.get(purviewKey) : '';
    const labels =
      typeof purviewValue === 'string' ? this.parsePurviewLabels(purviewValue) : undefined;
    if (!labels) {
      return UNREADABLE;
    }
    // A name entry is preferred, so the agent can be told the label's name when one is configured.
    const configured =
      labels.map(({ name }) => this.excludedLabels.get(name?.toLowerCase() ?? '')).find(Boolean) ??
      labels.map(({ id }) => this.excludedLabels.get(id)).find(Boolean);
    if (configured) {
      return {
        verdict: SensitivityVerdict.Excluded,
        label: configured,
        configuredById: GUID_PATTERN.test(configured),
      };
    }
    // Graph cuts the value at 255 characters in some responses, which can lose a label's name.
    if (this.excludesLabelNames && labels.some(({ name }) => name === undefined)) {
      return UNREADABLE;
    }
    return ALLOWED;
  }

  // One group of `MSIP_Label_<id>_<field>=<value>;` entries per label.
  private parsePurviewLabels(value: string): PurviewLabel[] | undefined {
    if (!value.trim()) {
      return [];
    }
    const names = new Map<string, string | undefined>();
    for (const [, id = '', field, fieldValue] of value.matchAll(PURVIEW_ENTRY_PATTERN)) {
      const labelId = id.toLowerCase();
      const name = field?.toLowerCase() === 'name' ? fieldValue : undefined;
      names.set(labelId, name ?? names.get(labelId));
    }
    if (names.size === 0) {
      return undefined;
    }
    return [...names].map(([id, name]) => ({ id, name }));
  }
}

const PURVIEW_LABELS_PROPERTY = 'String {00020386-0000-0000-C000-000000000046} Name msip_labels';
const LEGACY_SENSITIVITY_PROPERTY = 'Integer 0x0036';
// Graph answers with its own spelling of a requested id: `Integer 0x36` for `Integer 0x0036`, and
// the property set GUID in lower case.
const canonicalPropertyId = (id: string): string =>
  id.toLowerCase().replace(/\b0x0*([0-9a-f]+)\b/g, '0x$1');
const KNOWN_PROPERTIES = new Set(
  [PURVIEW_LABELS_PROPERTY, LEGACY_SENSITIVITY_PROPERTY].map(canonicalPropertyId),
);

const LEGACY_VALUES = new Map<string, LegacySensitivity | null>([
  ['0', null],
  ['1', LegacySensitivity.Personal],
  ['2', LegacySensitivity.Private],
  ['3', LegacySensitivity.Confidential],
]);

// As Outlook shows the flag.
const LEGACY_DISPLAY_NAMES: Record<LegacySensitivity, string> = {
  [LegacySensitivity.Personal]: 'Personal',
  [LegacySensitivity.Private]: 'Private',
  [LegacySensitivity.Confidential]: 'Confidential',
};

const GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PURVIEW_ENTRY_PATTERN =
  /MSIP_Label_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_([A-Za-z]+)=([^;]*)/gi;

const extendedPropertiesSchema = z.array(z.object({ id: z.string(), value: z.string().nullish() }));

interface PurviewLabel {
  id: string;
  name: string | undefined;
}
