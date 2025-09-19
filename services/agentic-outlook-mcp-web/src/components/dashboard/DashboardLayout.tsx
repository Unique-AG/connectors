import { ReactNode } from 'react';
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import { AppSidebar } from './Sidebar';

interface DashboardLayoutProps {
  children: ReactNode;
}

export const DashboardLayout = ({ children }: DashboardLayoutProps) => {
  return (
    <SidebarProvider defaultOpen={true}>
      <div className="min-h-screen flex w-full bg-background">
        <AppSidebar />

        <div className="flex-1 flex flex-col">
          <header className="h-16 border-b bg-card shadow-soft flex items-center px-6 gap-4">
            <SidebarTrigger className="lg:hidden" />

            <div className="flex-1">
              <h1 className="text-xl font-semibold text-foreground">Admin Dashboard</h1>
            </div>
          </header>

          {/* Main Content */}
          <main className="flex-1 p-6 bg-muted/30">{children}</main>
        </div>
      </div>
    </SidebarProvider>
  );
};
