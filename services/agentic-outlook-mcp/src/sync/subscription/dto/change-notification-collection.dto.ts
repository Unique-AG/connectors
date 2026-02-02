export class ChangeNotificationCollectionDto {
  public value?: ChangeNotificationDto[];
}

export class ChangeNotificationDto {
  public changeType?: 'created' | 'updated' | 'deleted';
  public clientState?: string | null;
  public encryptedContent?: unknown;
  public id?: string | null;
  public lifecycleEvent?: string | null;
  public resource?: string;
  public resourceData?: unknown;
  public subscriptionExpirationDateTime?: string;
  public subscriptionId?: string;
  public tenantId?: string;
}
