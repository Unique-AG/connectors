import { Save, Settings as SettingsIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export default function Settings() {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-foreground mb-2">Email Settings</h1>
          <p className="text-muted-foreground">
            Configure email synchronization settings and server preferences.
          </p>
        </div>
        <Button className="bg-gradient-primary hover:opacity-90">
          <Save className="h-4 w-4 mr-2" />
          Save Settings
        </Button>
      </div>

      <Card className="shadow-medium">
        <CardHeader>
          <CardTitle>Configuration</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center h-64">
          <div className="text-center text-muted-foreground">
            <SettingsIcon className="h-16 w-16 mx-auto mb-4 opacity-50" />
            <p>Settings configuration interface will be implemented here</p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
