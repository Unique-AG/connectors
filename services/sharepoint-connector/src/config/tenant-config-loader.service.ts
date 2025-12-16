import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { load as loadYaml } from 'js-yaml';
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
export class TenantConfigLoaderService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private cachedConfigs: SiteConfig[] | null = null;
  private cachedTenantConfig: TenantConfig | null = null;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
  ) {}

  public onModuleInit() {
    try {
      this.loadTenantConfig();
    } catch (error) {
      this.logger.error({
        msg: 'Failed to load tenant config during module initialization',
        error: sanitizeError(error),
      });
      throw error;
    }
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
      throw new Error(
        `Unknown site configuration source: ${tenantConfig.sitesConfigurationSource}`,
      );
    }

    return this.cachedConfigs;
  }

  private loadTenantConfig(): TenantConfig {
    if (this.cachedTenantConfig !== null) {
      return this.cachedTenantConfig;
    }

    const configPath = this.configService.get('app.tenantConfigDirectory', {
      infer: true,
    });

    if (!existsSync(configPath)) {
      throw new Error(`Tenant config directory not found at ${configPath}`);
    }

    const files = readdirSync(configPath).filter(
      (file) => file.endsWith('.yaml') || file.endsWith('.yml'),
    );

    if (files.length === 0) {
      throw new Error(`No tenant configuration files found in ${configPath}`);
    }

    const tenantFile = files[0];
    if (!tenantFile) {
      throw new Error(`Failed to get first tenant config file from ${configPath}`);
    }

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
    if (!tenantConfig.sites || tenantConfig.sites.length === 0) {
      throw new Error('No site configurations found in tenant config with inline source');
    }

    this.logger.debug(`Loaded ${tenantConfig.sites.length} site configs from inline tenant config`);

    const activeConfigs = this.filterActiveConfigs(tenantConfig.sites);
    this.logger.log(`Loaded ${activeConfigs.length} active site configs from inline configuration`);

    return activeConfigs;
  }

  private async loadSiteConfigsFromSharePointList(
    tenantConfig: TenantConfig,
  ): Promise<SiteConfig[]> {
    const listUrl = tenantConfig.sitesConfigSourceListUrl;

    if (!listUrl) {
      throw new Error(
        'sitesConfigSourceListUrl must be specified in tenant config when using sharePointList source',
      );
    }

    this.logger.log(`Loading site configs from SharePoint list: ${listUrl}`);

    try {
      const { siteId, listId } = await this.graphApiService.extractSiteAndListIdFromUrl(listUrl);

      this.logger.debug(`Extracted site ID: ${siteId}, list ID: ${listId}`);

      const listItems = await this.graphApiService.getListItemsForConfig(siteId, listId);

      const configs: SiteConfig[] = [];
      for (const item of listItems) {
        try {
          const validatedConfig = SiteConfigSchema.parse(item.fields);
          configs.push(validatedConfig);
        } catch (error) {
          if (error instanceof ZodError) {
            this.logger.error({
              msg: `Invalid site config from SharePoint list item`,
              itemId: item.id,
              errors: error.issues,
            });
            throw new Error(
              `Invalid site config in SharePoint list item ${item.id}: ${error.message}`,
            );
          }
          throw error;
        }
      }

      const activeConfigs = this.filterActiveConfigs(configs);
      this.logger.log(
        `Loaded ${activeConfigs.length} active site configs from SharePoint list (${configs.length} total items)`,
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

  private filterActiveConfigs(configs: SiteConfig[]): SiteConfig[] {
    return configs.filter((config) => config.syncStatus === 'active');
  }
}
