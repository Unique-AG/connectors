import {Config as UniqueApiConfig} from './unique-api.config'
import {Config as PipelineConfig} from './pipeline.config'
import {Config as SharepointConfig} from './sharepoint.config'

export type Config = UniqueApiConfig & PipelineConfig & SharepointConfig