import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../config';
import {DriveItem, ListItem} from "./types/sharepoint.types";

@Injectable()
export class FileFilterService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public isListItemValidForIngestion(fields: ListItem['fields']) {
    return Boolean(
      fields.FileLeafRef &&
        typeof fields.FileLeafRef === 'string' &&
        fields.FileLeafRef.toLowerCase().endsWith('.aspx') &&
        fields.FinanceGPTKnowledge === true &&
        fields._ModerationStatus === 0,
    );
  }

  public isFileValidForIngestion(item: DriveItem): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const syncColumnName = this.configService.get('sharepoint.syncColumnName', { infer: true });
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });

    if (
      !item.file ||
      !item.id ||
      !item.name ||
      !item.size ||
      !item.webUrl ||
      !item.lastModifiedDateTime ||
      !item.listItem?.fields ||
      item.size === 0
    ) {
      return false;
    }

    const isAspxFile = item.name?.toLowerCase().endsWith('.aspx');
    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);
    const hasSyncFlag = fields[syncColumnName] === true;

    return Boolean(hasSyncFlag && (isAllowedMimeType || isAspxFile));
  }
}
