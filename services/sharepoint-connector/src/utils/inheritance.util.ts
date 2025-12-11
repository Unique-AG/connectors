import { ConfigService } from '@nestjs/config';
import type { Config } from '../config';
import {
  DEFAULT_INHERITANCE_SETTINGS,
  InheritanceSettings,
  NO_INHERITANCE_SETTINGS,
} from './inheritance.constants';

export const resolveInheritanceSettings = (
  configService: ConfigService<Config, true>,
): InheritanceSettings => {
  // If using content_and_permissions sync, never inherit
  if (configService.get('processing.syncMode', { infer: true }) === 'content_and_permissions') {
    return NO_INHERITANCE_SETTINGS;
  }

  const inheritSettings = configService.get('unique.inheritModes', { infer: true });

  return inheritSettings ?? DEFAULT_INHERITANCE_SETTINGS;
};
