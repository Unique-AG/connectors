import { Injectable } from '@nestjs/common';
import { TenantConfigLoaderService } from '../../config/tenant-config-loader.service';
import { isModerationStatusApproved } from '../../constants/moderation-status.constants';
import { DriveItem, ListItem } from './types/sharepoint.types';

@Injectable()
export class FileFilterService {
  public constructor(private readonly tenantConfigLoaderService: TenantConfigLoaderService) {}

  public isListItemValidForIngestion(fields: ListItem['fields']) {
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const syncColumnName = tenantConfig.sites?.[0]?.syncColumnName;

    if (!syncColumnName) {
      return false;
    }

    return Boolean(
      fields.FileLeafRef?.toLowerCase().endsWith('.aspx') &&
        fields[syncColumnName] === true &&
        isModerationStatusApproved(fields._ModerationStatus),
    );
  }

  public isFileValidForIngestion(item: DriveItem): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const syncColumnName = tenantConfig.sites?.[0]?.syncColumnName;
    const allowedMimeTypes = tenantConfig.processingAllowedMimeTypes;
    const maxFileSizeBytes = tenantConfig.processingMaxFileSizeBytes;

    if (
      !item.file ||
      !item.id ||
      !item.name ||
      !item.size ||
      !item.webUrl ||
      !item.lastModifiedDateTime ||
      !item.listItem?.fields ||
      item.size === 0 ||
      !syncColumnName ||
      !allowedMimeTypes ||
      maxFileSizeBytes === undefined
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
