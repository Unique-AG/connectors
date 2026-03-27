import { Effect, Layer, Match } from "effect"
import type { DelegatedAuth } from "../Auth/MsGraphAuth"
import {
  InvalidRequestError,
  RateLimitedError,
  ResourceNotFoundError,
} from "../Errors/errors"
import type { MsGraphError } from "../Errors/errors"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage } from "../Schemas/OData"
import { PlannerPlanSchema, PlannerTaskSchema } from "../Schemas/PlannerTask"
import type { CreatePlannerTaskPayload, PlannerTask } from "../Schemas/PlannerTask"
import { PlannerService } from "./PlannerService"

const PlannerPlanPageSchema = ODataPage(PlannerPlanSchema)
const PlannerTaskPageSchema = ODataPage(PlannerTaskSchema)

const narrowToRateLimitOrNotFound = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.orElse(
    () => new ResourceNotFoundError({ resource: "planner", id: "unknown" }),
  ),
)

const narrowToRateLimitOrInvalidRequest = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    () => new RateLimitedError({ retryAfter: 0, resource: "planner" }),
  ),
)

const narrowToRateLimitNotFoundOrInvalidRequest = Match.type<MsGraphError>().pipe(
  Match.tag("RateLimitedError", (e) => e),
  Match.tag("ResourceNotFound", (e) => e),
  Match.tag("InvalidRequest", (e) => e),
  Match.orElse(
    () => new RateLimitedError({ retryAfter: 0, resource: "planner" }),
  ),
)

export const PlannerServiceLive = Layer.effect(
  PlannerService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    const listPlans = Effect.fn("PlannerService.listPlans")(
      function* (groupId: string) {
        return yield* http
          .get(`/groups/${groupId}/planner/plans`, PlannerPlanPageSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const getPlan = Effect.fn("PlannerService.getPlan")(
      function* (planId: string) {
        return yield* http
          .get(`/planner/plans/${planId}`, PlannerPlanSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const listTasks = Effect.fn("PlannerService.listTasks")(
      function* (planId: string) {
        return yield* http
          .get(`/planner/plans/${planId}/tasks`, PlannerTaskPageSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const getTask = Effect.fn("PlannerService.getTask")(
      function* (taskId: string) {
        return yield* http
          .get(`/planner/tasks/${taskId}`, PlannerTaskSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    const createTask = Effect.fn("PlannerService.createTask")(
      function* (task: CreatePlannerTaskPayload) {
        return yield* http
          .post("/planner/tasks", task, PlannerTaskSchema)
          .pipe(Effect.mapError(narrowToRateLimitOrInvalidRequest))
      },
    )

    const updateTask = Effect.fn("PlannerService.updateTask")(
      function* (taskId: string, etag: string, patch: Partial<CreatePlannerTaskPayload>) {
        return yield* http
          .patch(`/planner/tasks/${taskId}`, patch, PlannerTaskSchema, {
            "If-Match": etag,
          })
          .pipe(Effect.mapError(narrowToRateLimitNotFoundOrInvalidRequest))
      },
    )

    const deleteTask = Effect.fn("PlannerService.deleteTask")(
      function* (taskId: string, etag: string) {
        return yield* http
          .delete(`/planner/tasks/${taskId}`, { "If-Match": etag })
          .pipe(Effect.mapError(narrowToRateLimitOrNotFound))
      },
    )

    return PlannerService.of({
      listPlans,
      getPlan,
      listTasks,
      getTask,
      createTask,
      updateTask,
      deleteTask,
    })
  }),
) as Layer.Layer<
  PlannerService,
  never,
  MsGraphHttpClient | DelegatedAuth
>
