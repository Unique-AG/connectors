import { Injectable } from '@nestjs/common';
import {
  UniqueAccessType,
  UniqueEntityType,
} from './fetch-or-create-outlook-emails-root-scope.command';

export interface UniqueFile {
  id: string;
  fileAccess: FileAccessKey[];
  key: string;
  ownerType: string;
  ownerId: string;
}

type FileAccessModifier = 'R' | 'W' | 'M'; // Read / Write / Manage
type FileGranteeType = 'u' | 'g'; // User / Group

// Examples: u:343324546486501384W, g:group_pgrlo68tvvy5n38lr2le6tetR
export type FileAccessKey = `${FileGranteeType}:${string}${FileAccessModifier}`;

export interface UniqueFileAccessInput {
  contentId: string;
  accessType: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}

@Injectable()
export class UniqueFilesService {
  public async getFilesByKeys(_keys: string[]): Promise<UniqueFile[]> {
    return [];
  }
}
