import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { ModerationStatusValue } from '../../constants/moderation-status.constants';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { SharePointUser } from '../../microsoft-apis/graph/types/sharepoint.types';
import { SharepointContentItem } from '../../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFileIngestionService } from '../../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import {
  AuthorMetadata,
  ContentMetadata,
  ContentRegistrationRequest,
} from '../../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { normalizeError } from '../../utils/normalize-error';
import { buildIngestionItemKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.ContentRegistration;
  private readonly sharepointBaseUrl: string;

  public constructor(
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    const itemKey = buildIngestionItemKey(context.pipelineItem);

    const contentRegistrationRequest: ContentRegistrationRequest = {
      key: itemKey,
      title: context.pipelineItem.fileName,
      mimeType: context.mimeType ?? DEFAULT_MIME_TYPE,
      ownerType: UniqueOwnerType.Scope,
      scopeId: context.scopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      url: context.knowledgeBaseUrl,
      baseUrl: this.sharepointBaseUrl,
      byteSize: context.fileSize ?? 0,
      metadata: this.extractMetadata(context.pipelineItem),
    };

    context.metadata = contentRegistrationRequest.metadata;

    const syncMode = this.configService.get('processing.syncMode', { infer: true });
    // We add permissions only for new files, because existing ones should already have correct
    // permissions (including service user permissions) and we don't want to override them.
    if (syncMode === 'content_and_permissions' && context.fileStatus === 'new') {
      contentRegistrationRequest.fileAccess = [
        `u:${context.syncContext.serviceUserId}R`,
        `u:${context.syncContext.serviceUserId}W`,
        `u:${context.syncContext.serviceUserId}M`,
      ];
    }

    this.logger.debug(
      `contentRegistrationRequest: ${JSON.stringify(
        {
          url: contentRegistrationRequest.url,
          baseUrl: contentRegistrationRequest.baseUrl,
          key: contentRegistrationRequest.key,
          sourceName: contentRegistrationRequest.sourceName,
        },
        null,
        4,
      )}`,
    );

    try {
      const registrationResponse = await this.uniqueFileIngestionService.registerContent(
        contentRegistrationRequest,
      );

      assert.ok(
        registrationResponse.writeUrl,
        'Registration response missing required fields: id or writeUrl',
      );

      context.uploadUrl = this.correctWriteUrl(registrationResponse.writeUrl);
      context.uniqueContentId = registrationResponse.id;
      context.registrationResponse = registrationResponse;
      const _stepDuration = Date.now() - stepStartTime;

      return context;
    } catch (error) {
      const message = normalizeError(error).message;
      this.logger.error({
        msg: 'Content registration failed',
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: context.pipelineItem.siteId,
        error: message,
      });
      throw error;
    }
  }
  // PowerAutomate connector sends the raw body from Get_file_properties as metadata.
  // We replicate this by getting all fields from the SharePoint item
  // and adding additional fields that are available from the MS Graph API response.
  // AuthorLookupId and EditorLookupId are included in the fields, but we cannot
  // resolve them to full user objects (email, displayName) via MS Graph API like the
  // SharePoint REST API does.
  private extractMetadata(item: SharepointContentItem): ContentMetadata {
    const isListItem = item.itemType === 'listItem';
    const baseFields = isListItem ? item.item.fields : item.item.listItem.fields;
    const webUrl = isListItem ? item.item.webUrl : item.item.listItem.webUrl;
    const createdBy = isListItem ? item.item.createdBy : item.item.listItem.createdBy;

    const moderationStatus = isListItem
      ? (baseFields._ModerationStatus as ModerationStatusValue)
      : undefined;
    const metadata: ContentMetadata = {
      ...baseFields,
      Url: webUrl,
      Path: item.folderPath,
      DriveId: item.driveId,
      Link: webUrl,
      ItemInternalId: item.item.id,
      Filename: baseFields.FileLeafRef,
      ...(moderationStatus !== undefined && {
        ModerationStatus: moderationStatus,
      }),
      ...(createdBy?.user && {
        Author: this.extractAuthor(createdBy),
      }),
    };

    return metadata;
  }

  private extractAuthor(createdBy: { user: SharePointUser }): AuthorMetadata {
    return {
      email: createdBy.user.email,
      displayName: createdBy.user.displayName,
      id: createdBy.user.id,
    };
  }

  // HACK:
  // When running in internal auth mode, rewrite the writeUrl to route through the ingestion
  // service's scoped upload endpoint. This enables internal services to upload files without
  // requiring external network access (hairpinning).
  // Ideally we should fix this somehow in the service itself by using a separate property or make
  // writeUrl configurable, but for now this hack lets us avoid hairpinning issues in the internal
  // upload flows.
  private correctWriteUrl(writeUrl: string): string {
    const uniqueAuthMode = this.configService.get('unique.serviceAuthMode', { infer: true });
    if (uniqueAuthMode === 'external') {
      return writeUrl;
    }
    const url = new URL(writeUrl);
    const key = url.searchParams.get('key');
    assert.ok(key, 'writeUrl is missing key parameter');

    const ingestionApiUrl = this.configService.get('unique.ingestionServiceBaseUrl', {
      infer: true,
    });
    return `${ingestionApiUrl}/scoped/upload?key=${encodeURIComponent(key)}`;
  }
}
