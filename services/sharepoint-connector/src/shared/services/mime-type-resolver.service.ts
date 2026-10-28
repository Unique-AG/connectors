import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { lookup } from 'mime-types';
import { entries, map, pipe, sortBy } from 'remeda';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';

// mime-db has no entry for these; the default allowed MIME types list SharePoint pages under this one.
const MIME_TYPES_MISSING_FROM_LOOKUP: Readonly<Record<string, string>> = {
  '.asp': 'application/x-asp',
  '.aspx': 'application/x-asp',
};

@Injectable()
export class MimeTypeResolverService {
  private readonly sortedEntries: ReadonlyArray<
    readonly [fileNameSuffix: string, mimeType: string]
  >;

  public constructor(configService: ConfigService<Config, true>) {
    const overrides = configService.get('processing.mimeTypeOverridesByExtension', { infer: true });
    this.sortedEntries = pipe(
      overrides,
      entries(),
      map(([suffix, mimeType]) => [suffix.toLowerCase(), mimeType] as const),
      sortBy(([suffix]) => -suffix.length),
    );
  }

  public resolve(fileName: string, rawMimeType: string | undefined): string {
    const lowerFileName = fileName.toLowerCase();
    const match = this.sortedEntries.find(([suffix]) => lowerFileName.endsWith(suffix));
    if (match) {
      return match[1];
    }
    if (rawMimeType) {
      return rawMimeType;
    }

    const extensionStart = lowerFileName.lastIndexOf('.');
    const extension = extensionStart >= 0 ? lowerFileName.slice(extensionStart) : '';
    return MIME_TYPES_MISSING_FROM_LOOKUP[extension] || lookup(lowerFileName) || DEFAULT_MIME_TYPE;
  }
}
