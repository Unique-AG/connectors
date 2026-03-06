import { CreateSubscriptionRequest, UpdateSubscriptionRequest } from './subscriptions.requests';
import { Subscription } from './subscriptions.schema';

export class SubscriptionsClient {
  public constructor(private readonly fetch: typeof globalThis.fetch) {}

  public async create(params: CreateSubscriptionRequest): Promise<Subscription> {
    const response = await this.fetch('/subscriptions', {
      method: 'POST',
      body: JSON.stringify(CreateSubscriptionRequest.parse(params)),
    });
    return Subscription.parse(await response.json());
  }

  public async update(params: UpdateSubscriptionRequest): Promise<Subscription> {
    const response = await this.fetch(`/subscriptions/${params.subscriptionId}`, {
      method: 'PATCH',
      body: JSON.stringify(UpdateSubscriptionRequest.parse(params)),
    });
    return Subscription.parse(await response.json());
  }

  public async delete(params: { subscriptionId: string }): Promise<void> {
    await this.fetch(`/subscriptions/${params.subscriptionId}`, { method: 'DELETE' });
  }
}
