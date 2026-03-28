import { Effect, ServiceMap } from 'effect';
import type {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from '../errors/errors.js';
import type { ODataPageType } from '../schemas/odata.schema.js';
import type { CreatePlannerTaskPayload, PlannerPlan, PlannerTask } from './planner-task.schema.js';

export class PlannerService extends ServiceMap.Service<
  PlannerService,
  {
    readonly listPlans: (
      groupId: string,
    ) => Effect.Effect<ODataPageType<PlannerPlan>, ResourceNotFoundError | RateLimitedError>;

    readonly getPlan: (
      planId: string,
    ) => Effect.Effect<PlannerPlan, ResourceNotFoundError | RateLimitedError>;

    readonly listTasks: (
      planId: string,
    ) => Effect.Effect<ODataPageType<PlannerTask>, ResourceNotFoundError | RateLimitedError>;

    readonly getTask: (
      taskId: string,
    ) => Effect.Effect<PlannerTask, ResourceNotFoundError | RateLimitedError>;

    readonly createTask: (
      task: CreatePlannerTaskPayload,
    ) => Effect.Effect<PlannerTask, RateLimitedError | InvalidRequestError>;

    readonly updateTask: (
      taskId: string,
      etag: string,
      patch: Partial<CreatePlannerTaskPayload>,
    ) => Effect.Effect<PlannerTask, ResourceNotFoundError | RateLimitedError | InvalidRequestError>;

    readonly deleteTask: (
      taskId: string,
      etag: string,
    ) => Effect.Effect<void, ResourceNotFoundError | RateLimitedError>;
  }
>()('MsGraph/Planner/PlannerService') {}
