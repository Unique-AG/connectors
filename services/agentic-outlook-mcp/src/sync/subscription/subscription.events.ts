export class SubscriptionEvent {
  public constructor(
    public readonly subscriptionId: string,
    public readonly subscriptionForId: string,
    public readonly changeType: 'created' | 'updated' | 'deleted',
    public readonly resourceData: {
      '@odata.type': string;
      '@odata.id': string;
      id: string;
    },
  ) {}
}
