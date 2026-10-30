import { createZodDto } from 'nestjs-zod';
import * as z from 'zod';

export const ConsentDecisionSchema = z.object({
  session_id: z.string().min(1),
  csrf_token: z.string().min(1),
  decision: z.enum(['approve', 'deny']),
});

export class ConsentDecisionDto extends createZodDto(ConsentDecisionSchema) {}
