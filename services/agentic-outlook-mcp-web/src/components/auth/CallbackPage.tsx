import { useEffect } from 'react';
import { useAuth as useOidcAuth } from 'react-oidc-context';
import { useNavigate } from 'react-router-dom';

export const CallbackPage = () => {
  const oidcAuth = useOidcAuth();
  const navigate = useNavigate();

  useEffect(() => {
    // Handle the callback
    if (oidcAuth.isAuthenticated) {
      navigate('/dashboard', { replace: true });
    } else if (oidcAuth.error) {
      console.error('Authentication error:', oidcAuth.error);
      navigate('/login', { replace: true });
    }
  }, [oidcAuth.isAuthenticated, oidcAuth.error, navigate]);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="text-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
        <h2 className="text-xl font-semibold text-gray-700">Completing authentication...</h2>
        <p className="text-gray-500 mt-2">Please wait while we redirect you.</p>
      </div>
    </div>
  );
};
