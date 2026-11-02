import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { isModerationStatusApproved } from '../../constants/moderation-status.constants';
import { MimeTypeResolverService } from '../../shared/services/mime-type-resolver.service';
import type { Smeared } from '../../utils/smeared';
import { DriveItem, ListItem } from './types/sharepoint.types';

@Injectable()
export class FileFilterService {
  public constructor(
    private readonly configService: ConfigService<Config, true>,
    private readonly mimeTypeResolverService: MimeTypeResolverService,
  ) {}

  public isAttachmentValidForIngestion({
    fileName,
    size,
  }: {
    fileName: Smeared;
    size: number;
  }): boolean {
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });
    const maxFileSizeToIngestBytes = this.configService.get('processing.maxFileSizeToIngestBytes', {
      infer: true,
    });
    const mimeType = this.mimeTypeResolverService.resolve(fileName.value, undefined);
    return size > 0 && size <= maxFileSizeToIngestBytes && allowedMimeTypes.includes(mimeType);
  }

  public isGenericListItemInScope(fields: ListItem['fields'], syncColumnName: string): boolean {
    const moderationApproved =
      fields._ModerationStatus === undefined ||
      isModerationStatusApproved(fields._ModerationStatus);
    return fields[syncColumnName] === true && moderationApproved && fields.Attachments === true;
  }

  public isListItemValidForIngestion(fields: ListItem['fields'], syncColumnName: string) {
    return Boolean(
      fields.FileLeafRef?.toLowerCase().endsWith('.aspx') &&
        fields[syncColumnName] === true &&
        isModerationStatusApproved(fields._ModerationStatus),
    );
  }

  public isFileValidForIngestion(item: DriveItem, syncColumnName: string): boolean {
    const fields = item.listItem?.fields as Record<string, unknown>;
    const allowedMimeTypes = this.configService.get('processing.allowedMimeTypes', { infer: true });
    const maxFileSizeToIngestBytes = this.configService.get('processing.maxFileSizeToIngestBytes', {
      infer: true,
    });

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

    if (item.size > maxFileSizeToIngestBytes) {
      return false;
    }

    const isAspxFile = item.name?.toLowerCase().endsWith('.aspx');
    const resolvedMimeType = this.mimeTypeResolverService.resolve(item.name, item.file.mimeType);
    const isAllowedMimeType = allowedMimeTypes.includes(resolvedMimeType);
    const hasSyncFlag = fields[syncColumnName] === true;

    return Boolean(hasSyncFlag && (isAllowedMimeType || isAspxFile));
  }
}
