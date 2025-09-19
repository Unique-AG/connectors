import { LogOut } from 'lucide-react';
import { ReactNode } from 'react';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/contexts/AuthContext';

interface DashboardLayoutProps {
  children: ReactNode;
}

export const DashboardLayout = ({ children }: DashboardLayoutProps) => {
  const { user, logout } = useAuth();

  return (
    <div className="min-h-screen bg-background">
      <header className="h-16 border-b bg-card shadow-soft flex items-center px-6 gap-4">
        <div className="flex-1">
          <h1 className="text-xl font-semibold text-foreground">Admin Dashboard</h1>
        </div>

        {user && (
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 bg-primary text-primary-foreground rounded-full flex items-center justify-center text-sm font-medium">
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="hidden sm:block">
                <div className="text-sm font-medium">{user.name}</div>
                <div className="text-xs text-muted-foreground">{user.email}</div>
              </div>
            </div>

            <Button
              onClick={logout}
              variant="outline"
              size="sm"
              className="flex items-center gap-2"
            >
              <LogOut className="h-4 w-4" />
              Sign Out
            </Button>
          </div>
        )}
      </header>

      <main className="p-6 bg-muted/30 min-h-[calc(100vh-4rem)]">{children}</main>
    </div>
  );
};
