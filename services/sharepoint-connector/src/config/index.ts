import { AppConfig } from './app.config';
import { PipelineConfig } from './pipeline.config';
import { SharepointConfig } from './sharepoint.config';
import { UniqueApiConfig } from './unique-api.config';

export type Config = UniqueApiConfig & PipelineConfig & SharepointConfig & AppConfig;
