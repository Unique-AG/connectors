export const INHERITANCE_MODES = [
  'inherit_scopes_and_files',
  'inherit_scopes',
  'inherit_files',
  'none',
] as const;

export type InheritanceMode = (typeof INHERITANCE_MODES)[number];

export type InheritanceSettings = {
  inheritScopes: boolean;
  inheritFiles: boolean;
};

export const INHERITANCE_PRESETS: Record<InheritanceMode, InheritanceSettings> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
};

export const DEFAULT_INHERITANCE_SETTINGS: InheritanceSettings =
  INHERITANCE_PRESETS.inherit_scopes_and_files;
export const NO_INHERITANCE_SETTINGS: InheritanceSettings = INHERITANCE_PRESETS.none;

export const resolveInheritanceSettings = (
  inheritMode?: InheritanceMode,
): InheritanceSettings => {
  // Use inheritMode if available
  if (inheritMode) {
    switch (inheritMode) {
      case 'inherit_scopes':
        return INHERITANCE_PRESETS.inherit_scopes;
      case 'inherit_files':
        return INHERITANCE_PRESETS.inherit_files;
      case 'inherit_scopes_and_files':
        return INHERITANCE_PRESETS.inherit_scopes_and_files;
      default:
        return DEFAULT_INHERITANCE_SETTINGS;
    }
  }

  return DEFAULT_INHERITANCE_SETTINGS;
};
