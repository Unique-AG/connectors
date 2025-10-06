import {PipelineStep, ProcessingContext} from '../types/processing-context';

export interface IPipelineStep {
  readonly stepName: PipelineStep;
  execute: (context: ProcessingContext) => Promise<ProcessingContext>;
  cleanup?: (context: ProcessingContext) => Promise<void>;
}
