import { createContext, ReactNode, useContext, useMemo } from 'react';
import { AuthProvider as OidcAuthProvider, useAuth as useOidcAuth } from 'react-oidc-context';
import getOidcConfig, { mapOidcUserToAppUser } from '../config/oidc.config';

interface User {
  id: string;
  email: string;
  name: string;
  accessToken?: string;
  refreshToken?: string;
}

interface AuthContextType {
  user: User | null;
  login: () => void;
  logout: () => void;
  isLoading: boolean;
  isAuthenticated: boolean;
  error: Error | null;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: ReactNode;
}

const AuthContextProvider = ({ children }: { children: ReactNode }) => {
  const oidcAuth = useOidcAuth();

  const user = useMemo(() => {
    return mapOidcUserToAppUser(oidcAuth.user);
  }, [oidcAuth.user]);

  const login = () => {
    // Trigger OIDC sign in redirect
    void oidcAuth.signinRedirect();
  };

  const logout = () => {
    // Sign out and clear tokens
    void oidcAuth.signoutRedirect();
  };

  const value: AuthContextType = {
    user,
    login,
    logout,
    isLoading: oidcAuth.isLoading,
    isAuthenticated: oidcAuth.isAuthenticated,
    error: oidcAuth.error,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const AuthProvider = ({ children }: AuthProviderProps) => {
  const oidcConfig = getOidcConfig();

  return (
    <OidcAuthProvider {...oidcConfig}>
      <AuthContextProvider>{children}</AuthContextProvider>
    </OidcAuthProvider>
  );
};
