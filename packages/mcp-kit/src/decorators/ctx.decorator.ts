import { MCP_CTX_PARAM_INDEX } from '../constants';
import { invariant } from '../errors/defect.js';

export function Ctx(): ParameterDecorator {
  return (target, propertyKey, parameterIndex) => {
    invariant(propertyKey !== undefined, '@Ctx() must be applied to a method parameter, not a constructor parameter');
    Reflect.defineMetadata(MCP_CTX_PARAM_INDEX, parameterIndex, target, propertyKey);
  };
}
