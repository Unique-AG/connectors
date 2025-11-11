import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftAuthenticationService } from './auth/microsoft-authentication.service';
import { FileFilterService } from './graph/file-filter.service';
import { GraphApiService } from './graph/graph-api.service';
import { GraphClientFactory } from './graph/graph-client.factory';
import { GraphAuthenticationService } from './graph/middlewares/graph-authentication.service';
import { SharepointRestClientService } from './sharepoint-rest/sharepoint-rest-client.service';
import { SharepointRestHttpService } from './sharepoint-rest/sharepoint-rest-http.service';

@Module({
  imports: [ConfigModule],
  providers: [
    MicrosoftAuthenticationService,
    GraphClientFactory,
    FileFilterService,
    GraphAuthenticationService,
    GraphApiService,
    SharepointRestHttpService,
    SharepointRestClientService,
  ],
  exports: [GraphApiService, SharepointRestClientService],
})
export class MicrosoftApisModule {}
