import { AuthMode } from '../../../config/confluence.schema';
import type { Redacted } from '../../../utils/redacted';
import { ConfluenceAuth } from '../confluence-auth';

interface PatAuthConfig {
  mode: typeof AuthMode.PAT;
  token: Redacted<string>;
}

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
