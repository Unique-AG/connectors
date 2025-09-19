import { Lock, Mail, Waves } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useAuth } from '@/contexts/AuthContext';
import { useToast } from '@/hooks/use-toast';

export const LoginPage = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const { login, isLoading } = useAuth();
  const { toast } = useToast();

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-background via-muted to-primary/5 p-4">
      <Card className="w-full max-w-md shadow-strong">
        <CardHeader className="text-center space-y-4">
          <div className="mx-auto w-16 h-16 bg-gradient-primary rounded-full flex items-center justify-center shadow-medium">
            <Waves className="h-8 w-8 text-primary-foreground" />
          </div>
          <div>
            <CardTitle className="text-2xl font-bold bg-gradient-primary bg-clip-text text-transparent">
              Agentic Outlook MCP Server
            </CardTitle>
            <CardDescription className="text-muted-foreground">
              Sign in to manage your Outlook folder sync
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>  
          <Button
            type="submit"
            className="w-full bg-gradient-primary hover:opacity-90 transition-all duration-200 shadow-medium"
            disabled={isLoading}
          >
            {isLoading ? (
              <div className="flex items-center gap-2">
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary-foreground"></div>
                Signing in...
              </div>
            ) : (
              'Sign in with Microsoft'
            )}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
};
