import { Inject, Injectable } from '@nestjs/common';
import { Client } from 'undici';
import { SHAREPOINT_REST_HTTP_CLIENT } from '../../http-client.tokens';
import { MicrosoftAuthenticationService } from '../auth/microsoft-authentication.service';

@Injectable()
export class SharepointRestClientService {
  public constructor(
    @Inject(SHAREPOINT_REST_HTTP_CLIENT) private readonly httpClient: Client,
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
  ) {}

  public async request<T>(siteName: string, apiPath: string): Promise<T> {
    const token = await this.microsoftAuthenticationService.getAccessToken('sharepoint-rest');
    const cleanedApiPath = apiPath.startsWith('/') ? apiPath.slice(1) : apiPath;
    const path = `/sites/${siteName}/_api/${cleanedApiPath}`;
    const { statusCode, body } = await this.httpClient.request({
      method: 'GET',
      path,
      headers: {
        'Content-Type': 'application/json;odata=nometadata',
        Accept: 'application/json;odata=nometadata',
        Authorization: `Bearer ${token}`,
      },
    });

    if (statusCode < 200 || statusCode >= 300) {
      throw new Error(`Failed to request SharePoint endpoint ${path}: ${statusCode}`);
    }

    return body.json() as Promise<T>;
  }
}
