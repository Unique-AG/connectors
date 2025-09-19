import { UserPlus, Users as UsersIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function Users() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">User Management</h1>
          <p className="text-muted-foreground">
            Manage user accounts and permissions for the admin dashboard.
          </p>
        </div>
        <Button className="bg-gradient-primary hover:opacity-90">
          <UserPlus className="h-4 w-4 mr-2" />
          Add User
        </Button>
      </div>

      <Card className="shadow-medium">
        <CardHeader>
          <CardTitle>Users</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-64">
          <div className="text-center text-muted-foreground">
            <UsersIcon className="h-16 w-16 mx-auto mb-4 opacity-50" />
            <p>User management interface will be implemented here</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
