import type {DriveItem} from '@microsoft/microsoft-graph-types';
import {Injectable} from '@nestjs/common';
import {ConfigService} from '@nestjs/config';
import {Config} from '../config';

type DefinedFileProperties = 'file' | 'id' | 'name' | 'size' | 'webUrl' | 'listItem' | 'lastModifiedDateTime'

@Injectable()
export class FileFilterService {
  public constructor(private readonly configService: ConfigService<Config, true>) {
  }

  public isFileValidForIngestion(item: DriveItem): item is Omit<DriveItem, DefinedFileProperties> & { [key in DefinedFileProperties]: Exclude<DriveItem[key], null | undefined> } {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const syncColumnName = this.configService.get('sharepoint.syncColumnName', { infer: true });
    const allowedMimeTypes = this.configService.get('sharepoint.allowedMimeTypes', { infer: true });

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

    const isAllowedMimeType = item.file?.mimeType && allowedMimeTypes.includes(item.file.mimeType);
    const hasSyncFlag = fields[syncColumnName] === true;
    return Boolean(hasSyncFlag && isAllowedMimeType);
  }
}

