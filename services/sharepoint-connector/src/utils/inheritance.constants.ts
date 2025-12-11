export type InheritanceSettings = {
  inheritScopes: boolean;
  inheritFiles: boolean;
};

export const INHERITANCE_PRESETS: Record<
  'inherit_scopes_and_files' | 'inherit_scopes' | 'inherit_files' | 'none',
  InheritanceSettings
> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
};

export const DEFAULT_INHERITANCE_SETTINGS: InheritanceSettings =
  INHERITANCE_PRESETS.inherit_scopes_and_files;
export const NO_INHERITANCE_SETTINGS: InheritanceSettings = INHERITANCE_PRESETS.none;
