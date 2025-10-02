import type { DriveItem } from '@microsoft/microsoft-graph-types';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';

@Injectable()
export class FileFilterService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService) {}

  public isFileSyncable(item: DriveItem): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const syncColumnName = <string>this.configService.get('sharepoint.syncColumnName');
    const allowedMimeTypes = <string[]>this.configService.get('sharepoint.allowedMimeTypes')

    if (!item.file || !item.id || !item.name || !item.size || !item.webUrl) {
      this.logger.debug(
        `File missing required fields: id=${item.id}, name=${item.name}, size=${item.size}, webUrl=${item.webUrl}`,
      );
      return false;
    }

    if (!item.listItem?.fields) {
      this.logger.debug(`File ${item.name} has no listItem fields, skipping`);
      return false;
    }
   
    if (item.size === 0) {
      this.logger.debug(
        `File ${item.name} is empty (0 bytes), skipping to prevent ingestion failure`,
      );
      return false;
    }

    const hasSyncFlag = fields[syncColumnName] === true;
    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);

    return Boolean(hasSyncFlag && isAllowedMimeType);;
  }
}
