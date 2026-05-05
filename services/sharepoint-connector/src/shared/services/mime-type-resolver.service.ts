import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { entries, map, pipe, sortBy } from 'remeda';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';

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
    return match ? match[1] : (rawMimeType ?? DEFAULT_MIME_TYPE);
  }
}
