export const EnabledDisabledMode = {
  Enabled: 'enabled',
  Disabled: 'disabled',
} as const;

export type EnabledDisabledMode = (typeof EnabledDisabledMode)[keyof typeof EnabledDisabledMode];
