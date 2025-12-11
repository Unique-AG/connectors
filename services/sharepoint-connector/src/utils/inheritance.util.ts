import { ConfigService } from '@nestjs/config';
import { Config } from '../config';

export type InheritanceMode =
  | 'inherit_scopes_and_files'
  | 'inherit_scopes'
  | 'inherit_files'
  | 'none';

export interface InheritanceSettings {
  inheritScopes: boolean;
  inheritFiles: boolean;
}

// Predefined inheritance presets
const INHERITANCE_PRESETS: Record<InheritanceMode, InheritanceSettings> = {
  inherit_scopes_and_files: { inheritScopes: true, inheritFiles: true },
  none: { inheritScopes: false, inheritFiles: false },
  inherit_scopes: { inheritScopes: true, inheritFiles: false },
  inherit_files: { inheritScopes: false, inheritFiles: true },
};

export const resolveInheritanceSettings = (
  configService: ConfigService<Config, true>,
): InheritanceSettings => {
  // If using content_and_permissions sync, never inherit
  if (configService.get('processing.syncMode', { infer: true }) === 'content_and_permissions') {
    return INHERITANCE_PRESETS.none;
  }

  const inheritModes = configService.get('unique.inheritModes', { infer: true }) ?? 'inherit_scopes_and_files'; 
  return INHERITANCE_PRESETS[inheritModes];
};
