import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { isModerationStatusApproved } from '../../constants/moderation-status.constants';
import { DriveItem, ListItem } from './types/sharepoint.types';

@Injectable()
export class FileFilterService {
  public constructor(private readonly configService: ConfigService<Config, true>) {}

  public isListItemValidForIngestion(fields: ListItem['fields']) {
    return Boolean(
      fields.FileLeafRef?.toLowerCase().endsWith('.aspx') &&
        fields.FinanceGPTKnowledge === true &&
        isModerationStatusApproved(fields._ModerationStatus),
    );
  }

  public isFileValidForIngestion(item: DriveItem): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const syncColumnName = this.configService.get('sharepoint.syncColumnName', { infer: true });
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });
    const maxFileSizeBytes = this.configService.get('processing.maxFileSizeBytes', { infer: true });

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

    if (item.size > maxFileSizeBytes) {
      return false;
    }

    const isAspxFile = item.name?.toLowerCase().endsWith('.aspx');
    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);
    const hasSyncFlag = fields[syncColumnName] === true;

    return Boolean(hasSyncFlag && (isAllowedMimeType || isAspxFile));
  }
}
