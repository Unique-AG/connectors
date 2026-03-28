import { Effect, Layer } from 'effect';
import type { DelegatedAuth } from '../Auth/MsGraphAuth';
import {
  toNotFoundOrRateLimit,
  toNotFoundRateLimitOrInvalid,
  toRateLimitOrInvalid,
} from '../Errors/errorNarrowers';
import { MsGraphHttpClient } from '../Http/MsGraphHttpClient';
import { ODataPage } from '../Schemas/OData';
import type { CreatePlannerTaskPayload } from '../Schemas/PlannerTask';
import { PlannerPlanSchema, PlannerTaskSchema } from '../Schemas/PlannerTask';
import { PlannerService } from './PlannerService';

const PlannerPlanPageSchema = ODataPage(PlannerPlanSchema);
const PlannerTaskPageSchema = ODataPage(PlannerTaskSchema);

export const PlannerServiceLive = Layer.effect(
  PlannerService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient;

    const listPlans = Effect.fn('PlannerService.listPlans')(
      function* (groupId: string) {
        const path = `/groups/${groupId}/planner/plans`;
        return yield* http
          .get(path, PlannerPlanPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'listPlans' }),
    );

    const getPlan = Effect.fn('PlannerService.getPlan')(
      function* (planId: string) {
        const path = `/planner/plans/${planId}`;
        return yield* http
          .get(path, PlannerPlanSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'getPlan' }),
    );

    const listTasks = Effect.fn('PlannerService.listTasks')(
      function* (planId: string) {
        const path = `/planner/plans/${planId}/tasks`;
        return yield* http
          .get(path, PlannerTaskPageSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'listTasks' }),
    );

    const getTask = Effect.fn('PlannerService.getTask')(
      function* (taskId: string) {
        const path = `/planner/tasks/${taskId}`;
        return yield* http
          .get(path, PlannerTaskSchema)
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'getTask' }),
    );

    const createTask = Effect.fn('PlannerService.createTask')(
      function* (task: CreatePlannerTaskPayload) {
        return yield* http
          .post('/planner/tasks', task, PlannerTaskSchema)
          .pipe(Effect.mapError(toRateLimitOrInvalid('/planner/tasks')));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'createTask' }),
    );

    const updateTask = Effect.fn('PlannerService.updateTask')(
      function* (taskId: string, etag: string, patch: Partial<CreatePlannerTaskPayload>) {
        const path = `/planner/tasks/${taskId}`;
        return yield* http
          .patch(path, patch, PlannerTaskSchema, { 'If-Match': etag })
          .pipe(Effect.mapError(toNotFoundRateLimitOrInvalid(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'updateTask' }),
    );

    const deleteTask = Effect.fn('PlannerService.deleteTask')(
      function* (taskId: string, etag: string) {
        const path = `/planner/tasks/${taskId}`;
        return yield* http
          .delete(path, { 'If-Match': etag })
          .pipe(Effect.mapError(toNotFoundOrRateLimit(path)));
      },
      Effect.annotateLogs({ service: 'PlannerService', method: 'deleteTask' }),
    );

    return PlannerService.of({
      listPlans,
      getPlan,
      listTasks,
      getTask,
      createTask,
      updateTask,
      deleteTask,
    });
  }).pipe(Effect.withSpan('PlannerServiceLive.initialize')),
) as Layer.Layer<PlannerService, never, MsGraphHttpClient | DelegatedAuth>;
