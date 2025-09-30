/** biome-ignore-all lint/suspicious/noExplicitAny: window object as any is ok */

import { PowerSyncContext } from '@powersync/react';
import {
  createContext,
  FC,
  PropsWithChildren,
  Suspense,
  useEffect,
  useMemo,
  useState,
} from 'react';
import { useAuth } from 'react-oidc-context';
import { Connector } from '../lib/powersync/connector';
import { powerSyncDb } from '../lib/powersync/database';

type SystemProviderProps = PropsWithChildren;

export const ConnectorContext = createContext<Connector | null>(null);

(window as any).db = powerSyncDb;

export const SystemProvider: FC<SystemProviderProps> = ({ children }) => {
  const { user, isAuthenticated } = useAuth();
  const [powerSync] = useState(powerSyncDb);
  const connector = useMemo(() => {
    if (!isAuthenticated || !user) return null;
    return new Connector(user);
  }, [user, isAuthenticated]);

  useEffect(() => {
    if (!connector) return;
    (window as any)._powersync = powerSync;

    powerSync.init();
    powerSync.connect(connector);
  }, [connector, powerSync]);

  return (
    <Suspense fallback={<div>Loading...</div>}>
      <PowerSyncContext.Provider value={powerSync}>
        <ConnectorContext.Provider value={connector}>{children}</ConnectorContext.Provider>
      </PowerSyncContext.Provider>
    </Suspense>
  );
};
