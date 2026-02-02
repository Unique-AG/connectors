/** biome-ignore-all lint/suspicious/noExplicitAny: Fork of KurtzL/nestjs-temporal */
/** biome-ignore-all lint/complexity/noBannedTypes: Fork of KurtzL/nestjs-temporal */
import { Injectable, Type } from '@nestjs/common';
import { Reflector } from '@nestjs/core';
import {
  TEMPORAL_MODULE_ACTIVITIES,
  TEMPORAL_MODULE_ACTIVITY,
  TEMPORAL_MODULE_WORKFLOW,
  TEMPORAL_MODULE_WORKFLOW_METHOD,
} from './temporal.constants';

@Injectable()
export class TemporalMetadataAccessor {
  public constructor(private readonly reflector: Reflector) {}

  public isActivities(target: Type<any> | Function): boolean {
    if (!target) return false;
    return !!this.reflector.get(TEMPORAL_MODULE_ACTIVITIES, target);
  }

  public getActivities(target: Type<any> | Function): any {
    return this.reflector.get(TEMPORAL_MODULE_ACTIVITIES, target);
  }

  public isActivity(target: Type<any> | Function): boolean {
    if (!target) return false;
    return !!this.reflector.get(TEMPORAL_MODULE_ACTIVITY, target);
  }

  public getActivity(target: Type<any> | Function): any {
    return this.reflector.get(TEMPORAL_MODULE_ACTIVITY, target);
  }

  public isWorkflows(target: Type<any> | Function): boolean {
    if (!target) return false;
    return !!this.reflector.get(TEMPORAL_MODULE_WORKFLOW, target);
  }

  public getWorkflows(target: Type<any> | Function): any {
    return this.reflector.get(TEMPORAL_MODULE_WORKFLOW, target);
  }

  public isWorkflowMethod(target: Type<any> | Function): boolean {
    if (!target) return false;
    return !!this.reflector.get(TEMPORAL_MODULE_WORKFLOW_METHOD, target);
  }

  public getWorkflowMethod(target: Type<any> | Function): any {
    return this.reflector.get(TEMPORAL_MODULE_WORKFLOW_METHOD, target);
  }
}
