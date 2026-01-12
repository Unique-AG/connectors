import assert from 'node:assert';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Config } from '../../config';
import { getInheritanceSettings } from '../../config/tenant-config.schema';
import { DEFAULT_MIME_TYPE } from '../../constants/defaults.constants';
import { INGESTION_SOURCE_KIND, INGESTION_SOURCE_NAME } from '../../constants/ingestion.constants';
import { ModerationStatusValue } from '../../constants/moderation-status.constants';
import { StoreInternallyMode } from '../../constants/store-internally-mode.enum';
import { UniqueOwnerType } from '../../constants/unique-owner-type.enum';
import { SharePointUser } from '../../microsoft-apis/graph/types/sharepoint.types';
import { SharepointContentItem } from '../../microsoft-apis/graph/types/sharepoint-content-item.interface';
import { UniqueFileIngestionService } from '../../unique-api/unique-file-ingestion/unique-file-ingestion.service';
import {
  AuthorMetadata,
  ContentMetadata,
  ContentRegistrationRequest,
} from '../../unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { concealIngestionKey, redact, shouldConcealLogs, smear } from '../../utils/logging.util';
import { sanitizeError } from '../../utils/normalize-error';
import { buildIngestionItemKey } from '../../utils/sharepoint.util';
import type { ProcessingContext } from '../types/processing-context';
import { PipelineStep } from '../types/processing-context';
import type { IPipelineStep } from './pipeline-step.interface';

@Injectable()
export class ContentRegistrationStep implements IPipelineStep {
  private readonly logger = new Logger(this.constructor.name);
  public readonly stepName = PipelineStep.ContentRegistration;
  private readonly sharepointBaseUrl: string;
  private readonly shouldConcealLogs: boolean;

  public constructor(
    private readonly uniqueFileIngestionService: UniqueFileIngestionService,
    private readonly configService: ConfigService<Config, true>,
  ) {
    this.sharepointBaseUrl = this.configService.get('sharepoint.baseUrl', { infer: true });
    this.shouldConcealLogs = shouldConcealLogs(this.configService);
  }

  public async execute(context: ProcessingContext): Promise<ProcessingContext> {
    const stepStartTime = Date.now();

    const itemKey = buildIngestionItemKey(context.pipelineItem);

    const contentRegistrationRequest: ContentRegistrationRequest = {
      key: itemKey,
      title: context.pipelineItem.fileName,
      mimeType: context.mimeType ?? DEFAULT_MIME_TYPE,
      ownerType: UniqueOwnerType.Scope,
      scopeId: context.targetScopeId,
      sourceOwnerType: UniqueOwnerType.Company,
      sourceKind: INGESTION_SOURCE_KIND,
      sourceName: INGESTION_SOURCE_NAME,
      url: context.knowledgeBaseUrl,
      baseUrl: this.sharepointBaseUrl,
      byteSize: context.fileSize ?? 0,
      metadata: this.extractMetadata(context.pipelineItem),
      storeInternally: context.syncContext.siteConfig.storeInternally === StoreInternallyMode.Enabled,
    };

    context.metadata = contentRegistrationRequest.metadata;

    const { inheritFiles } = getInheritanceSettings(context.syncContext.siteConfig);
    // We add permissions only for new files, because existing ones should already have correct
    // permissions (including service user permissions) and we don't want to override them; applies
    // when inheritance is disabled or when syncing permissions.
    if (!inheritFiles && context.fileStatus === 'new') {
      contentRegistrationRequest.fileAccess = [
        `u:${context.syncContext.serviceUserId}R`,
        `u:${context.syncContext.serviceUserId}W`,
        `u:${context.syncContext.serviceUserId}M`,
      ];
    }

    this.logger.debug(
      `contentRegistrationRequest: ${JSON.stringify(
        {
          url: this.shouldConcealLogs
            ? redact(contentRegistrationRequest.url ?? '')
            : contentRegistrationRequest.url,
          baseUrl: this.shouldConcealLogs
            ? redact(contentRegistrationRequest.baseUrl ?? '')
            : contentRegistrationRequest.baseUrl,
          key: this.shouldConcealLogs
            ? concealIngestionKey(contentRegistrationRequest.key)
            : contentRegistrationRequest.key,
          correlationId: context.correlationId,
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
      this.logger.error({
        msg: 'Content registration failed',
        correlationId: context.correlationId,
        itemId: context.pipelineItem.item.id,
        driveId: context.pipelineItem.driveId,
        siteId: this.shouldConcealLogs
          ? smear(context.pipelineItem.siteId)
          : context.pipelineItem.siteId,
        error: sanitizeError(error),
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
