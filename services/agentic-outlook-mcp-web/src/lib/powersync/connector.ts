import type { AbstractPowerSyncDatabase, PowerSyncBackendConnector } from '@powersync/web';
import { User } from 'oidc-client-ts';
import { BatchDtoDataItemType } from '../../@generated/agenticOutlookMCPAPI.schemas';
import { batch } from '../../@generated/batch/batch';

export interface Config {
  backendUrl: string;
  clientId: string;
  powersyncUrl: string;
}

export class Connector implements PowerSyncBackendConnector {
  private readonly config: Config;
  private readonly user: User;
  private clientId: string | null = null;

  public constructor(user: User) {
    this.config = {
      backendUrl: import.meta.env.VITE_BACKEND_URL,
      clientId: import.meta.env.VITE_OAUTH_CLIENT_ID,
      powersyncUrl: import.meta.env.VITE_POWERSYNC_URL,
    };
    this.user = user;
    console.log('Connector initialized.', this.config, this.user.profile.sub);
  }

  public async fetchCredentials() {
    const { access_token } = this.user;
    if (!access_token) throw new Error('User not authenticated.');

    return {
      endpoint: this.config.powersyncUrl,
      token: access_token,
    };
  }

  public async uploadData(database: AbstractPowerSyncDatabase) {
    console.log('Uploading data');
    if (!this.clientId) this.clientId = await database.getClientId();
    const transaction = await database.getNextCrudTransaction();
    if (!transaction) return;

    const data = transaction.crud.map((entry) => {
      if (!Object.keys(BatchDtoDataItemType).includes(entry.table)) {
        console.error(`Invalid table: ${entry.table}`);
        throw new Error(`Invalid table: ${entry.table}`);
      }
      return {
        ...entry.toJSON(),
        type: entry.table as BatchDtoDataItemType,
      };
    });

    try {
      const response = await batch(
        {
          clientId: this.clientId,
          data,
        },
        { headers: { Authorization: `Bearer ${this.user.access_token}` } },
      );

      if (response.status !== 200)
        throw new Error(
          `Received ${response.status} from /api/data: ${JSON.stringify(response.data)}`,
        );

      await transaction.complete();
    } catch (error) {
      console.error('Failed to upload data', error);
      throw error;
    }
  }
}
