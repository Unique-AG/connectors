import { AuthMode, ConfluenceConfig } from '../../../config/confluence.schema';
import { ConfluenceAuth } from '../confluence-auth.abstract';

type PatAuthConfig = Extract<ConfluenceConfig['auth'], { mode: typeof AuthMode.Pat }>;

export class PatAuthStrategy extends ConfluenceAuth {
  private readonly header: string;

  public constructor(authConfig: PatAuthConfig) {
    super();
    this.header = `Bearer ${authConfig.token.value}`;
  }

  public async getAuthorizationHeader(): Promise<string> {
    return this.header;
  }
}
