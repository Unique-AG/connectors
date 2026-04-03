import { MCP_CTX_PARAM_INDEX } from '../constants';
import { invariant } from '../errors/defect.js';

/**
 * Parameter decorator that marks a method parameter to receive the MCP request context object
 * (e.g. `RequestHandlerExtra` carrying auth info, session, and abort signal).
 * The parameter index is stored via `Reflect.defineMetadata` (key: `MCP_CTX_PARAM_INDEX`)
 * and the runtime bridge skips it when mapping MCP input arguments to the method signature.
 */
export function Ctx(): ParameterDecorator {
  return (target, propertyKey, parameterIndex) => {
    invariant(propertyKey !== undefined, '@Ctx() must be applied to a method parameter, not a constructor parameter');
    Reflect.defineMetadata(MCP_CTX_PARAM_INDEX, parameterIndex, target, propertyKey);
  };
}
