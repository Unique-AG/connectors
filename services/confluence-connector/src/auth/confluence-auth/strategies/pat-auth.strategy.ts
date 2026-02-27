import { AuthMode, ConfluenceConfig } from '../../../config/confluence.schema';
import { ConfluenceAuth } from '../confluence-auth.abstract';

type PatAuthConfig = Extract<ConfluenceConfig['auth'], { mode: typeof AuthMode.PAT }>;

export class PatAuthStrategy extends ConfluenceAuth {
  private readonly token: string;

  public constructor(authConfig: PatAuthConfig) {
    super();
    this.token = authConfig.token.value;
  }

  public async acquireToken(): Promise<string> {
    return this.token;
  }
}
