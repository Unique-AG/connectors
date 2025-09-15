import type { ProcessingContext } from '../types/processing-context';

export interface IPipelineStep {
  readonly stepName: string;
  execute: (context: ProcessingContext) => Promise<ProcessingContext>;
  cleanup?: (context: ProcessingContext) => Promise<void>;
}
