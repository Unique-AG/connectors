export type {
  BasicProxyConfig,
  NoAuthProxyConfig,
  NoneProxyConfig,
  ProxyConfig,
  ProxyConfigNamespaced,
  TlsProxyConfig,
} from './proxy.config';
export { ProxyConfigSchema, proxyConfig } from './proxy.config';
export { ProxyModule } from './proxy.module';
export {
  PROXY_MODULE_OPTIONS_TOKEN,
  type ProxyModuleOptions,
} from './proxy.module-definition';
export {
  type GetDispatcherOptions,
  type GetHttpAgentOptions,
  type ProxyMode,
  ProxyService,
} from './proxy.service';
