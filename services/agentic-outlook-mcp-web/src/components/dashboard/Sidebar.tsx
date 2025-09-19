import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  FolderTree,
  LogOut,
  Mail,
  Settings,
  Users,
  Waves,
} from 'lucide-react';
import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { useAuth } from '@/contexts/AuthContext';

const navigationItems = [
  {
    title: 'Folder Management',
    url: '/',
    icon: FolderTree,
    description: 'Manage Outlook folder sync',
  },
  {
    title: 'Analytics',
    url: '/analytics',
    icon: BarChart3,
    description: 'View sync statistics',
  },
  {
    title: 'User Management',
    url: '/users',
    icon: Users,
    description: 'Manage user accounts',
  },
  {
    title: 'Email Settings',
    url: '/settings',
    icon: Settings,
    description: 'Configure email sync',
  },
];

export const AppSidebar = () => {
  const { state } = useSidebar();
  const location = useLocation();
  const { user, logout } = useAuth();
  const collapsed = state === 'collapsed';

  const isActive = (path: string) => location.pathname === path;

  const getNavClassName = (active: boolean) =>
    active
      ? 'bg-primary text-primary-foreground shadow-soft'
      : 'hover:bg-muted transition-all duration-200';

  return (
    <Sidebar
      variant="inset"
      collapsible="icon"
      className="border-r shadow-soft"
    >
      <SidebarHeader className="p-6 border-b">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-gradient-primary rounded-lg flex items-center justify-center shadow-medium">
            <Waves className="h-5 w-5 text-primary-foreground" />
          </div>
          <div className="flex-1 group-data-[collapsible=icon]:hidden">
            <h2 className="text-lg font-bold text-foreground">Agentic Outlook MCP Server</h2>
            <p className="text-sm text-muted-foreground">Outlook Sync Manager</p>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent className="flex-1 p-4">
        <SidebarGroup>
          <SidebarGroupLabel>
            Main Navigation
          </SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="space-y-2">
              {navigationItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton
                    asChild
                    className={`${getNavClassName(isActive(item.url))} rounded-lg h-12`}
                  >
                    <NavLink to={item.url} end className="flex items-center gap-3 p-3">
                      <item.icon className="h-5 w-5 flex-shrink-0" />
                      <div className="flex-1 min-w-0">
                        <div className="font-medium">{item.title}</div>
                        <div className="text-xs opacity-70 truncate">{item.description}</div>
                      </div>
                    </NavLink>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="p-4 border-t">
        <div className="space-y-3">
          {user && (
            <div className="p-3 bg-muted rounded-lg group-data-[collapsible=icon]:hidden">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-primary text-primary-foreground rounded-full flex items-center justify-center text-sm font-medium">
                  {user.name.charAt(0).toUpperCase()}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium truncate">{user.name}</div>
                  <div className="text-xs text-muted-foreground truncate">{user.email}</div>
                </div>
              </div>
            </div>
          )}
          <Button
            onClick={logout}
            variant="outline"
            className="w-full justify-start group-data-[collapsible=icon]:w-10 group-data-[collapsible=icon]:h-10 group-data-[collapsible=icon]:p-0 transition-all duration-200"
          >
            <LogOut className="h-4 w-4" />
            <span className="ml-2 group-data-[collapsible=icon]:sr-only">Sign Out</span>
          </Button>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
};
