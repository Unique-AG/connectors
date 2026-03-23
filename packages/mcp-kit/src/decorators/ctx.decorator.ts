import { MCP_CTX_PARAM_INDEX } from '../constants';

export function Ctx(): ParameterDecorator {
  return (target, propertyKey, parameterIndex) => {
    Reflect.defineMetadata(MCP_CTX_PARAM_INDEX, parameterIndex, target, propertyKey!);
  };
}
