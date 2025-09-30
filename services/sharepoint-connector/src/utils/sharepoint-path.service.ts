import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import type { DriveItem } from '@microsoft/microsoft-graph-types';
import type { ProcessingContext } from '../processing-pipeline/types/processing-context';

@Injectable()
export class SharePointPathService {
  public constructor(private readonly configService: ConfigService) {}

  public generatePathBasedKey(file: DriveItem): string {
    const parentRef = file.parentReference as Record<string, unknown>;
    const path = String(parentRef?.path ?? '');
    const fileName = String(file.name ?? '');

    const siteName = String(parentRef?.siteName ?? parentRef?.siteId ?? '');
    const driveName = String(parentRef?.name ?? parentRef?.driveId ?? '');

    const folderPath = this.extractFolderPath(path);
    return this.buildKey(siteName, driveName, folderPath, fileName);
  }

  public generateFileKeyFromContext(context: ProcessingContext): string {
    const meta = context.metadata as Record<string, unknown>;
    const parentPath = String(meta.parentPath ?? '');
    const fileName = String(context.fileName);

    const siteName = String(meta.siteName ?? meta.siteId as string);
    const driveName = String(meta.driveName ?? meta.driveId as string);

    const folderPath = this.extractFolderPath(parentPath);
    return this.buildKey(siteName, driveName, folderPath, fileName);
  }

  private extractFolderPath(sharePointPath: string): string {
    return sharePointPath
      .replace(/^\/drive\/root:/i, '')
      .replace(/^:/i, '')
      .split('/')
      .filter(Boolean)
      .join('/');
  }

  private buildKey(siteName: string, driveName: string, folderPath: string, fileName: string): string {
    const scopeId = this.configService.get('uniqueApi.scopeId');
    const prefix = scopeId ? '' : 'sharepoint/';

    if (folderPath) {
      return `${prefix}${siteName}/${driveName}/${folderPath}/${fileName}`;
    }
    return `${prefix}${siteName}/${driveName}/${fileName}`;
  }
}
