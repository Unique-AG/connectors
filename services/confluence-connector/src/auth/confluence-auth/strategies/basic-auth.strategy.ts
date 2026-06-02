import { AuthMode, ConfluenceConfig } from '../../../config/confluence.schema';
import { ConfluenceAuth } from '../confluence-auth.abstract';

type BasicAuthConfig = Extract<ConfluenceConfig['auth'], { mode: typeof AuthMode.Basic }>;

export class BasicAuthStrategy extends ConfluenceAuth {
  private readonly header: string;

  public constructor(authConfig: BasicAuthConfig) {
    super();
    const credentials = `${authConfig.username}:${authConfig.password.value}`;
    this.header = `Basic ${Buffer.from(credentials, 'utf8').toString('base64')}`;
  }

  public async getAuthorizationHeader(): Promise<string> {
    return this.header;
  }
}
