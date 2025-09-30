import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { ModerationStatus } from './sharepoint.types';

@Injectable()
export class FileFilterService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService) {}

  public isFileSyncable(item: DriveItem): boolean {
    const syncColumnName = this.configService.get<string>('sharepoint.syncColumnName') as string;
    const allowedMimeTypes = this.configService.get<string[]>('sharepoint.allowedMimeTypes') as string[];
    const fields = item.listItem?.fields as Record<string, unknown> | undefined;

    if (!fields) {
      this.logger.debug(`File ${item.name} has no listItem fields, skipping`);
      return false;
    }

    const hasSyncFlag = (fields as Record<string, unknown>)[syncColumnName] === true;
    const moderation = (fields as Record<string, unknown>).OData__ModerationStatus as
      | ModerationStatus
      | undefined;
    const isApproved = moderation === ModerationStatus.Approved;
    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);

    // TODO moderation status not coming back from graph api && isApproved
    const syncable = Boolean(hasSyncFlag && isAllowedMimeType);

    if (!syncable) {
      this.logger.debug(
        `File ${item.name} not syncable - syncFlag: ${hasSyncFlag}, approved: ${isApproved}, allowedMimeType: ${isAllowedMimeType}`,
      );
    }

    return syncable;
  }

  public getAllowedMimeTypes(): string[] {
    return this.configService.get<string[]>('sharepoint.allowedMimeTypes') as string[];
  }

  public getSyncColumnName(): string {
    return this.configService.get<string>('sharepoint.syncColumnName') as string;
  }
}
