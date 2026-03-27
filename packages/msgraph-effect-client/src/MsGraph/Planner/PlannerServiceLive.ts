import { Effect, Layer } from "effect"
import type { MsGraphAuth } from "../Auth/MsGraphAuth"
import type { PlannerPermissions } from "../Auth/Permissions"
import { MsGraphHttpClient } from "../Http/MsGraphHttpClient"
import { ODataPage } from "../Schemas/OData"
import { PlannerPlanSchema, PlannerTaskSchema } from "../Schemas/PlannerTask"
import { PlannerService } from "./PlannerService"

const PlannerPlanPageSchema = ODataPage(PlannerPlanSchema)
const PlannerTaskPageSchema = ODataPage(PlannerTaskSchema)

export const PlannerServiceLive = Layer.effect(
  PlannerService,
  Effect.gen(function* () {
    const http = yield* MsGraphHttpClient

    return PlannerService.of({
      listPlans: (groupId) =>
        http.get(`/groups/${groupId}/planner/plans`, PlannerPlanPageSchema),

      getPlan: (planId) => http.get(`/planner/plans/${planId}`, PlannerPlanSchema),

      listTasks: (planId) =>
        http.get(`/planner/plans/${planId}/tasks`, PlannerTaskPageSchema),

      getTask: (taskId) => http.get(`/planner/tasks/${taskId}`, PlannerTaskSchema),

      createTask: (task) =>
        http.post("/planner/tasks", task, PlannerTaskSchema),

      updateTask: (taskId, etag, patch) =>
        http.patch(`/planner/tasks/${taskId}`, patch, PlannerTaskSchema, {
          "If-Match": etag,
        }),

      deleteTask: (taskId, etag) =>
        http.delete(`/planner/tasks/${taskId}`, { "If-Match": etag }),
    })
  }),
) as Layer.Layer<
  PlannerService,
  never,
  MsGraphHttpClient | MsGraphAuth<"Delegated", PlannerPermissions>
>
