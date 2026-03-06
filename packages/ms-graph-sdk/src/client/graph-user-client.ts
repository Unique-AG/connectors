import { OutlookClient } from '../outlook/outlook-client';
import { SubscriptionsClient } from '../shared/subscriptions-client';
import { TeamsClient } from '../teams/teams-client';

export class GraphUserClient {
  public readonly teams: TeamsClient;
  public readonly outlook: OutlookClient;
  public readonly subscriptions: SubscriptionsClient;

  public constructor(fetch: typeof globalThis.fetch) {
    this.teams = new TeamsClient(fetch);
    this.outlook = new OutlookClient(fetch);
    this.subscriptions = new SubscriptionsClient(fetch);
  }
}
