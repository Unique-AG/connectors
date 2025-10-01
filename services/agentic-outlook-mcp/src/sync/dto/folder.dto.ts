import { createZodDto } from 'nestjs-zod';
import { folderArraySchema, folderSchema } from '../../drizzle';

export class FolderDto extends createZodDto(folderSchema) {}
export class FolderArrayDto extends createZodDto(folderArraySchema) {}
