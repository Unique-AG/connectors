import { ConfigService } from '@nestjs/config';
import { Config } from '../config';

export type InheritanceMode = 'none' | 'inherit_scopes' | 'inherit_files';

export interface InheritanceSettings {
  inheritScopes: boolean;
  inheritFiles: boolean;
}

// Predefined inheritance presets
const INHERITANCE_PRESETS: Record<InheritanceMode | 'default', InheritanceSettings> = {
  default: { inheritScopes: true, inheritFiles: true },
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

  const modes = configService.get('unique.inheritModes', { infer: true }) as
    | InheritanceMode[]
    | undefined;

  // If no modes specified, use default (inherit everything)
  if (!modes?.length) {
    return INHERITANCE_PRESETS.default;
  }

  // If 'none' is explicitly set, don't inherit anything
  if (modes.includes('none')) {
    return INHERITANCE_PRESETS.none;
  }

  // Each mode independently enables its corresponding inheritance flag
  return {
    inheritScopes: modes.includes('inherit_scopes'),
    inheritFiles: modes.includes('inherit_files'),
  };
};
