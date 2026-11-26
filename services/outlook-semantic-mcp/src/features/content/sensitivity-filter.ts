import { Inject, Injectable } from '@nestjs/common';
import * as z from 'zod';
import { type FeaturesConfig, featuresConfig, LegacySensitivity } from '~/config';

export enum SensitivityVerdict {
  Allowed = 'allowed',
  Excluded = 'excluded',
  // The properties are missing or malformed, so the message is treated as excluded.
  Unreadable = 'unreadable',
}

// Mail is filtered on these properties after Graph returns it; see
// testing-utils/sensitivity-label-probe for how Graph exposes them.
@Injectable()
export class SensitivityFilter {
  public readonly isActive: boolean;
  public readonly expand =
    `singleValueExtendedProperties($filter=id eq '${PURVIEW_LABELS_PROPERTY}' or id eq '${LEGACY_SENSITIVITY_PROPERTY}')`;
  private readonly excludedLabels: ReadonlySet<string>;
  private readonly excludedLegacy: ReadonlySet<LegacySensitivity>;
  private readonly excludesLabelNames: boolean;

  public constructor(@Inject(featuresConfig.KEY) features: FeaturesConfig) {
    this.excludedLabels = features.sensitivityExclusions.labels;
    this.excludedLegacy = features.sensitivityExclusions.legacy;
    this.isActive = this.excludedLabels.size > 0 || this.excludedLegacy.size > 0;
    this.excludesLabelNames = [...this.excludedLabels].some((label) => !GUID_PATTERN.test(label));
  }

  public judge(properties: ExtendedProperty[] | undefined): SensitivityVerdict {
    if (!this.isActive) {
      return SensitivityVerdict.Allowed;
    }
    if (!properties) {
      return SensitivityVerdict.Unreadable;
    }
    const values = new Map(properties.map(({ id, value }) => [id.toLowerCase(), value ?? '']));
    // Graph ignores the $expand filter of a $search that does not select internetMessageHeaders and
    // returns other properties instead. Every message carries the legacy flag, 0 when unset.
    const legacyValue = values.get(LEGACY_SENSITIVITY_PROPERTY.toLowerCase());
    const legacy = legacyValue === undefined ? undefined : LEGACY_VALUES.get(legacyValue);
    if ([...values.keys()].some((id) => !KNOWN_PROPERTIES.has(id)) || legacy === undefined) {
      return SensitivityVerdict.Unreadable;
    }
    if (legacy !== null && this.excludedLegacy.has(legacy)) {
      return SensitivityVerdict.Excluded;
    }

    const labels = this.parsePurviewLabels(values.get(PURVIEW_LABELS_PROPERTY.toLowerCase()) ?? '');
    if (!labels) {
      return SensitivityVerdict.Unreadable;
    }
    const isExcluded = labels.some(
      ({ id, name }) =>
        this.excludedLabels.has(id) ||
        (name !== undefined && this.excludedLabels.has(name.toLowerCase())),
    );
    if (isExcluded) {
      return SensitivityVerdict.Excluded;
    }
    // Graph cuts the value at 255 characters in some responses, which can lose a label's name.
    if (this.excludesLabelNames && labels.some(({ name }) => name === undefined)) {
      return SensitivityVerdict.Unreadable;
    }
    return SensitivityVerdict.Allowed;
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
const KNOWN_PROPERTIES = new Set(
  [PURVIEW_LABELS_PROPERTY, LEGACY_SENSITIVITY_PROPERTY].map((id) => id.toLowerCase()),
);

const LEGACY_VALUES = new Map<string, LegacySensitivity | null>([
  ['0', null],
  ['1', LegacySensitivity.Personal],
  ['2', LegacySensitivity.Private],
  ['3', LegacySensitivity.Confidential],
]);

const GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const PURVIEW_ENTRY_PATTERN =
  /MSIP_Label_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})_([A-Za-z]+)=([^;]*)/gi;

export const extendedPropertiesSchema = z
  .array(z.object({ id: z.string(), value: z.string().nullish() }))
  .optional();

type ExtendedProperty = NonNullable<z.infer<typeof extendedPropertiesSchema>>[number];

interface PurviewLabel {
  id: string;
  name: string | undefined;
}
