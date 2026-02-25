import { gql } from 'graphql-request';
import { Content } from './content.dto';

export interface GetContentByIdQueryOutput {
  getContentById: Content;
}

export interface GetContentByIdQueryInput {
  contentId: string;
}

export const GET_CONTENT_BY_ID_QUERY = gql`
  query GetContentById($contentId: String!) {
    getContentById(contentId: $contentId) {
      appliedIngestionConfig
      byteSize
      companyId
      createdAt
      createdBy
      deletedAt
      description
      expiredAt
      expiresAt
      expiresInDays
      externalFileOwner
      fileAccess
      fileAccessState
      id
      ingestionConfig
      ingestionProgress
      ingestionState
      ingestionStateDetails
      ingestionStateUpdatedAt
      internallyStoredAt
      key
      metadata
      mimeType
      ownerId
      ownerType
      pdfPreviewWriteUrl
      previewPdfFileName
      title
      updatedAt
      url
      writeUrl
      chunks {
        companyId
        contentId
        createdAt
        createdBy
        embedding
        embeddingsFirst10
        endPage
        id
        model
        order
        startPage
        text
        updatedAt
        vectorId
      }
      readUrl
    }
  }
`;
