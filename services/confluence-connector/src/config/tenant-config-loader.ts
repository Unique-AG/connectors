import assert from 'node:assert';
import { globSync, readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { Logger } from '@nestjs/common';
import { load } from 'js-yaml';
import { isPlainObject } from 'remeda';
import { z } from 'zod';
import { ConfluenceConfigSchema } from './confluence.schema';
import { ProcessingConfigSchema } from './processing.schema';
import { UniqueConfigSchema } from './unique.schema';

const TENANT_NAME_REGEX = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const TENANT_CONFIG_SUFFIX = '-tenant-config.yaml';

const TenantStatus = {
  ACTIVE: 'active',
  INACTIVE: 'inactive',
  DELETED: 'deleted',
} as const;

const TenantStatusSchema = z.object({
  status: z.enum([TenantStatus.ACTIVE, TenantStatus.INACTIVE, TenantStatus.DELETED]).default(TenantStatus.ACTIVE),
});

const TenantConfigSchema = z.object({
  confluence: ConfluenceConfigSchema,
  unique: UniqueConfigSchema,
  processing: ProcessingConfigSchema,
});
export type TenantConfig = z.infer<typeof TenantConfigSchema>;

export interface NamedTenantConfig {
  name: string;
  config: TenantConfig;
}

const logger = new Logger('TenantConfigLoader');

let cachedConfigs: NamedTenantConfig[] | null = null;
export function getTenantConfigs(): NamedTenantConfig[] {
  if (!cachedConfigs) {
    const tenantConfigPathPattern = process.env.TENANT_CONFIG_PATH_PATTERN;
    assert.ok(
      tenantConfigPathPattern,
      'TENANT_CONFIG_PATH_PATTERN environment variable is not set',
    );
    cachedConfigs = loadTenantConfigs(tenantConfigPathPattern);
  }
  return cachedConfigs;
}

function extractTenantName(filePath: string): string {
  const filename = basename(filePath);
  assert.ok(
    filename.endsWith(TENANT_CONFIG_SUFFIX),
    `Tenant config filename '${filename}' does not end with '${TENANT_CONFIG_SUFFIX}'`,
  );
  return filename.slice(0, -TENANT_CONFIG_SUFFIX.length);
}

function validateTenantNames(entries: { name: string; path: string }[]): void {
  const seen = new Map<string, string>();
  for (const entry of entries) {
    assert.ok(
      TENANT_NAME_REGEX.test(entry.name),
      `Invalid tenant name '${entry.name}' extracted from '${entry.path}': must match ${TENANT_NAME_REGEX}`,
    );
    const existing = seen.get(entry.name);
    if (existing) {
      throw new Error(
        `Duplicate tenant name '${entry.name}' found in '${existing}' and '${entry.path}'`,
      );
    }
    seen.set(entry.name, entry.path);
  }
}

function loadTenantConfigs(pathPattern: string): NamedTenantConfig[] {
  const files = globSync(pathPattern);
  assert.ok(
    files.length > 0,
    `No tenant configuration files found matching pattern '${pathPattern}'`,
  );

  const entries = files.map((filePath) => ({
    name: extractTenantName(filePath),
    path: filePath,
  }));

  validateTenantNames(entries);

  const activeConfigs: NamedTenantConfig[] = [];

  for (const entry of entries) {
    try {
      const fileContent = readFileSync(entry.path, 'utf-8');
      const rawConfig = load(fileContent);
      assert.ok(
        isPlainObject(rawConfig),
        `Invalid tenant config: expected a plain object, got ${typeof rawConfig}`,
      );

      const { status } = TenantStatusSchema.parse(rawConfig);

      if (status === TenantStatus.DELETED) {
        logger.log(`Tenant '${entry.name}' is deleted, skipping`);
        continue;
      }

      const config = TenantConfigSchema.parse(rawConfig);

      if (status === TenantStatus.INACTIVE) {
        logger.log(`Tenant '${entry.name}' is inactive, skipping`);
        continue;
      }

      activeConfigs.push({ name: entry.name, config });
    } catch (error) {
      if (error instanceof Error) {
        throw new Error(
          `Failed to load or validate tenant config from ${entry.path}: ${error.message}`,
          { cause: error },
        );
      }
      throw error;
    }
  }

  assert.ok(
    activeConfigs.length > 0,
    'No active tenant configurations found. At least one tenant must have status "active".',
  );

  return activeConfigs;
}
