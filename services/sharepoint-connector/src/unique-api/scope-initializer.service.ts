import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import { UniqueApiService } from './unique-api.service';
import { UniqueAuthService } from './unique-auth.service';

@Injectable()
export class ScopeInitializerService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly uniqueAuthService: UniqueAuthService,
    private readonly uniqueApiService: UniqueApiService,
  ) {}

  public async initialize(scopeName: string): Promise<void> {
    const sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    const uniqueToken = await this.uniqueAuthService.getToken();

    const rootScope = await this.uniqueApiService.queryRootScopeByName(scopeName, uniqueToken);

    if (!rootScope) {
      this.logger.log(`Scope with name '${scopeName}' and parentId=null not found`);
      return;
    }

    if (rootScope.externalId) {
      this.logger.log(
        `Scope '${rootScope.name}' (id: ${rootScope.id}) already has externalId = '${rootScope.externalId}', skipping`,
      );
      return;
    }

    await this.uniqueApiService.updateScopeExternalId(rootScope.id, sharepointBaseUrl, uniqueToken);
    this.logger.log(
      `Updated scope '${rootScope.name}' (id: ${rootScope.id}) with externalId = '${sharepointBaseUrl}'`,
    );
  }
}
