import { AuthenticationProvider } from '@microsoft/microsoft-graph-client';
import { Injectable } from '@nestjs/common';
import { MicrosoftAuthenticationService } from '../../auth/microsoft-authentication.service';

@Injectable()
export class GraphAuthenticationService implements AuthenticationProvider {
  public constructor(
    private readonly microsoftAuthenticationService: MicrosoftAuthenticationService,
  ) {}

  public async getAccessToken(): Promise<string> {
    return await this.microsoftAuthenticationService.getAccessToken('graph');
  }
}
