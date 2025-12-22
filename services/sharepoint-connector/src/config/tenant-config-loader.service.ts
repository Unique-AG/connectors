import assert from 'node:assert';
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { load as loadYaml } from 'js-yaml';
import { redactSiteNameFromPath, shouldConcealLogs, smear } from 'src/utils/logging.util';
import { ZodError } from 'zod';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { sanitizeError } from '../utils/normalize-error';
import { Config } from './index';
import {
  SiteConfig,
  SiteConfigSchema,
  TenantConfig,
  TenantConfigSchema,
} from './tenant-config.schema';

@Injectable()
export class TenantConfigLoaderService {
  private readonly logger = new Logger(this.constructor.name);
  private readonly shouldConcealLogs: boolean;
  private cachedConfigs: SiteConfig[] | null = null;
  private cachedTenantConfig: TenantConfig | null = null;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
  ) {
    this.shouldConcealLogs = shouldConcealLogs(this);
  }

  public async loadConfig(): Promise<SiteConfig[]> {
    if (this.cachedConfigs !== null) {
      return this.cachedConfigs;
    }

    const tenantConfig = this.loadTenantConfig();

    if (tenantConfig.sitesConfigurationSource === 'inline') {
      this.cachedConfigs = this.loadSiteConfigsFromInline(tenantConfig);
    } else if (tenantConfig.sitesConfigurationSource === 'sharePointList') {
      this.cachedConfigs = await this.loadSiteConfigsFromSharePointList(tenantConfig);
    } else {
      assert.fail(`Unknown site configuration source: ${tenantConfig.sitesConfigurationSource}`);
    }


    return this.cachedConfigs;
  }

  public loadTenantConfig(): TenantConfig {
    if (this.cachedTenantConfig !== null) {
      return this.cachedTenantConfig;
    }

    const configPath = this.configService.get('app.tenantConfigDirectory', {
      infer: true,
    });

    assert.ok(existsSync(configPath), `Tenant config directory not found at ${configPath}`);

    const files = readdirSync(configPath).filter(
      (file) => file.endsWith('.yaml') || file.endsWith('.yml'),
    );

    assert.ok(files.length > 0, `No tenant configuration files found in ${configPath}`);

    // TODO to change when implementing multi tenant support
    const tenantFile = files[0];
    assert.ok(tenantFile, `Failed to get first tenant config file from ${configPath}`);

    if (files.length > 1) {
      this.logger.warn(
        `Multiple tenant config files found in ${configPath}. Using the first one: ${tenantFile}`,
      );
    }

    const filePath = resolve(configPath, tenantFile);
    const fileContent = readFileSync(filePath, 'utf-8');

    try {
      const parsedData = loadYaml(fileContent);
      this.cachedTenantConfig = TenantConfigSchema.parse(parsedData);
      this.logger.debug(`Loaded tenant config from ${tenantFile}`);
      return this.cachedTenantConfig;
    } catch (error) {
      if (error instanceof ZodError) {
        this.logger.error({
          msg: `Invalid tenant config in file: ${tenantFile}`,
          errors: error.issues,
        });
        throw new Error(`Invalid tenant config in file ${tenantFile}: ${error.message}`);
      }
      throw error;
    }
  }

  private loadSiteConfigsFromInline(tenantConfig: TenantConfig): SiteConfig[] {
    assert.ok(
      tenantConfig.sites && tenantConfig.sites.length > 0,
      'No site configurations found in tenant config with inline source',
    );

    this.logger.debug(`Loaded ${tenantConfig.sites.length} site configs from inline tenant config`);

    // TODO Check this logic for filtering active configs. We may return all and let caller take action on status.
    // TODO Check how we handle site deletions
    // TODO extract sync status to enum
    const activeConfigs = tenantConfig.sites.filter((config) => config.syncStatus === 'active');
    return activeConfigs;
  }

  private async loadSiteConfigsFromSharePointList(
    tenantConfig: TenantConfig,
  ): Promise<SiteConfig[]> {
    const listUrl = tenantConfig.sitesConfigListUrl;

    assert.ok(
      listUrl,
      'sitesConfigListUrl must be specified in tenant config when using sharePointList source',
    );

    this.logger.log(
      `Loading site configs from SharePoint list: ${this.shouldConcealLogs ? redactSiteNameFromPath(listUrl) : listUrl}`,
    );

    try {
      const { siteId, listId } = await this.graphApiService.extractSiteAndListIdFromUrl(listUrl);

      this.logger.debug(
        `Extracted site ID: ${this.shouldConcealLogs ? smear(siteId) : siteId}, list ID: ${listId}`,
      );

      const siteConfigList = await this.graphApiService.getSitesConfigList(siteId, listId);

      const siteConfigs: SiteConfig[] = [];
      for (const siteConfigListItem of siteConfigList) {
        try {
          const validatedConfig = SiteConfigSchema.parse(siteConfigListItem.fields);
          siteConfigs.push(validatedConfig);
        } catch (error) {
          if (error instanceof ZodError) {
            this.logger.error({
              msg: `Invalid site config from SharePoint list item`,
              itemId: siteConfigListItem.id,
              errors: error.issues,
            });
            throw new Error(
              `Invalid site config in SharePoint list item ${siteConfigListItem.id}: ${error.message}`,
            );
          }
          throw error;
        }
      }

      // TODO Check this logic for filtering active configs. We may return all and let caller take action on status.
      // TODO Check how we handle site deletions
      // TODO extract sync status to enum
      const activeConfigs = siteConfigs.filter((config) => config.syncStatus === 'active');
      this.logger.log(
        `Loaded ${activeConfigs.length} active site configs from SharePoint list (${siteConfigs.length} total items)`,
      );

      return activeConfigs;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to load site configs from SharePoint list',
        error: sanitizeError(error),
      });
      throw error;
    }
  }
}
