import { Logger } from '@nestjs/common';
import { AuthMode } from '../../../config/confluence.schema';
import type { Redacted } from '../../../utils/redacted';
import { ConfluenceAuth } from '../confluence-auth.abstract';

interface PatAuthConfig {
  mode: typeof AuthMode.PAT;
  token: Redacted<string>;
}

export class PatAuthStrategy extends ConfluenceAuth {
  private readonly logger = new Logger(PatAuthStrategy.name);
  private readonly token: string;

  public constructor(authConfig: PatAuthConfig) {
    super();
    this.token = authConfig.token.value;
  }

  public async acquireToken(): Promise<string> {
    this.logger.log('Acquiring Confluence PAT token');
    return this.token;
  }
}
