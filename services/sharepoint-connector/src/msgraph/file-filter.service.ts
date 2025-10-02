import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class FileFilterService {
  public constructor(private readonly configService: ConfigService) {}

  public isFileMarkedForSyncing(item: DriveItem): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const syncColumnName = <string>this.configService.get('sharepoint.syncColumnName');
    const allowedMimeTypes = <string[]>this.configService.get('sharepoint.allowedMimeTypes');

    if (
      !item.file ||
      !item.id ||
      !item.name ||
      !item.size ||
      !item.webUrl ||
      !item.listItem?.fields ||
      item.size === 0
    ) {
      return false;
    }

    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);
    const hasSyncFlag = fields[syncColumnName] === true;
    return Boolean(hasSyncFlag && isAllowedMimeType);
  }
}
