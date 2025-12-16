import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { Injectable, Logger, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { load as loadYaml } from 'js-yaml';
import { ZodError } from 'zod';
import { GraphApiService } from '../microsoft-apis/graph/graph-api.service';
import { sanitizeError } from '../utils/normalize-error';
import { Config } from './index';
import { SiteConfig, SiteConfigSchema, TenantConfigSchema } from './tenant-config.schema';

@Injectable()
export class TenantConfigLoaderService implements OnModuleInit {
  private readonly logger = new Logger(this.constructor.name);
  private cachedConfigs: SiteConfig[] | null = null;

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly graphApiService: GraphApiService,
  ) {}

  public onModuleInit() {
    try {
      this.loadConfigs();
    } catch (error) {
      this.logger.error({
        msg: 'Failed to load site configs during module initialization',
        error: sanitizeError(error),
      });
      throw error;
    }
  }

  public async getConfigs(): Promise<SiteConfig[]> {
    if (this.cachedConfigs !== null) {
      return this.cachedConfigs;
    }
    return this.loadConfigs();
  }

  private loadConfigs(): SiteConfig[] {
    const source = this.configService.get('app.sitesConfigurationSource', {
      infer: true,
    });

    if (source === 'sharePointList') {
      throw new Error(
        'sharePointList configuration source requires async loading. Use loadConfigsAsync() instead.',
      );
    }

    return this.loadConfigsFromDirectory();
  }

  public async loadConfigsAsync(): Promise<SiteConfig[]> {
    if (this.cachedConfigs !== null) {
      return this.cachedConfigs;
    }

    const source = this.configService.get('app.sitesConfigurationSource', {
      infer: true,
    });

    if (source === 'configDirectory') {
      this.cachedConfigs = this.loadConfigsFromDirectory();
    } else if (source === 'sharePointList') {
      this.cachedConfigs = await this.loadConfigsFromSharePointList();
    } else {
      throw new Error(`Unknown configuration source: ${source}`);
    }

    return this.cachedConfigs;
  }

  private loadConfigsFromDirectory(): SiteConfig[] {
    const configPath = this.configService.get('app.sitesConfigPath', {
      infer: true,
    });

    if (!existsSync(configPath)) {
      this.logger.warn(`Config directory not found at ${configPath}, returning empty configs`);
      return [];
    }

    const files = readdirSync(configPath).filter(
      (file) => file.endsWith('.json') || file.endsWith('.yaml') || file.endsWith('.yml'),
    );

    const configs: SiteConfig[] = [];

    for (const file of files) {
      try {
        const filePath = resolve(configPath, file);
        const fileContent = readFileSync(filePath, 'utf-8');

        let parsedData: unknown;

        if (file.endsWith('.json')) {
          parsedData = JSON.parse(fileContent);
        } else if (file.endsWith('.yaml') || file.endsWith('.yml')) {
          parsedData = loadYaml(fileContent);
        }

        // Check if this is a tenant config (has sharepointBaseUrl and ingestionServiceBaseUrl) or a direct site config
        const parsedObj = parsedData as Record<string, unknown>;
        if (
          typeof parsedObj.sharepointBaseUrl === 'string' &&
          typeof parsedObj.ingestionServiceBaseUrl === 'string'
        ) {
          // This is a self-contained tenant config
          try {
            const validatedTenant = TenantConfigSchema.parse(parsedData);
            this.logger.debug(
              `Loaded ${validatedTenant.sites.length} site configs from tenant file: ${file}`,
            );

            for (const siteConfig of validatedTenant.sites) {
              configs.push(siteConfig);
            }
          } catch (error) {
            if (error instanceof ZodError) {
              this.logger.error({
                msg: `Invalid tenant config in file: ${file}`,
                errors: error.issues,
              });
              throw new Error(`Invalid tenant config in file ${file}: ${error.message}`);
            }
            throw error;
          }
        } else if (Array.isArray(parsedObj.sites)) {
          // Legacy format: tenant config with nested sites but missing infrastructure URLs
          this.logger.warn(
            `File ${file} appears to be a legacy tenant config format. Please update to include sharepointBaseUrl and ingestionServiceBaseUrl.`,
          );
          for (const siteConfig of parsedObj.sites) {
            try {
              const validatedConfig = SiteConfigSchema.parse(siteConfig);
              configs.push(validatedConfig);
            } catch (error) {
              if (error instanceof ZodError) {
                this.logger.error({
                  msg: `Invalid site config in tenant file: ${file}`,
                  errors: error.issues,
                });
                throw new Error(`Invalid site config in tenant file ${file}: ${error.message}`);
              }
              throw error;
            }
          }
        } else {
          // This is a standalone site config file (backward compatibility)
          const validatedConfig = SiteConfigSchema.parse(parsedData);
          configs.push(validatedConfig);

          this.logger.debug(`Loaded site config from standalone file: ${file}`);
        }
      } catch (error) {
        if (error instanceof ZodError) {
          this.logger.error({
            msg: `Invalid config in file: ${file}`,
            errors: error.issues,
          });
          throw new Error(`Invalid config in file ${file}: ${error.message}`);
        }
        throw error;
      }
    }

    const activeConfigs = this.filterActiveConfigs(configs);
    this.logger.log(`Loaded ${activeConfigs.length} active site configs from directory`);

    return activeConfigs;
  }

  private async loadConfigsFromSharePointList(): Promise<SiteConfig[]> {
    const listUrl = this.configService.get('app.sitesConfigSourceListUrl', {
      infer: true,
    });

    if (!listUrl) {
      throw new Error(
        'SHAREPOINT_SITES_CONFIG_SOURCE_LIST_URL must be set when using sharePointList configuration source',
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
            this.logger.warn({
              msg: `Skipping invalid site config from list item`,
              itemId: item.id,
              errors: error.issues,
            });
            continue;
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
