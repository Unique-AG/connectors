import type { AbstractPowerSyncDatabase, PowerSyncBackendConnector } from '@powersync/web';
import { User } from 'oidc-client-ts';

export interface Config {
  backendUrl: string;
  clientId: string;
  powersyncUrl: string;
}

export class Connector implements PowerSyncBackendConnector {
  private readonly config: Config;
  private readonly user: User;

  public constructor(user: User) {
    this.config = {
      backendUrl: import.meta.env.VITE_BACKEND_URL,
      clientId: import.meta.env.VITE_OAUTH_CLIENT_ID,
      powersyncUrl: import.meta.env.VITE_POWERSYNC_URL,
    };
    this.user = user;
  }

  public async fetchCredentials() {
    const { access_token } = this.user;
    if (!access_token) throw new Error('User not authenticated.');

    return {
      endpoint: this.config.powersyncUrl,
      token: access_token,
    };
  }

  public async uploadData(database: AbstractPowerSyncDatabase) {}
}
