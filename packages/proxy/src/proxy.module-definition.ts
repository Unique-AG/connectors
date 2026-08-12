import { ConfigurableModuleBuilder } from '@nestjs/common';

export interface ProxyModuleOptions {
  isExternal: boolean;
}

export const { ConfigurableModuleClass, MODULE_OPTIONS_TOKEN: PROXY_MODULE_OPTIONS_TOKEN } =
  new ConfigurableModuleBuilder<ProxyModuleOptions>()
    .setExtras({ isGlobal: true }, (definition, extras) => ({
      ...definition,
      global: extras.isGlobal,
    }))
    .build();
