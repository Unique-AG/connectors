#!/usr/bin/env node

/**
 * Script to register the web client with the OAuth server
 * Run this once after starting the backend server
 */

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:3000';
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:5173';

async function registerClient() {
  const clientData = {
    client_name: 'Agentic Outlook MCP Web',
    client_description: 'Web interface for Agentic Outlook MCP',
    redirect_uris: [
      `${FRONTEND_URL}/callback`,
      'http://localhost:5173/callback', // Dev URL
      'http://localhost:4173/callback', // Preview URL
    ],
    grant_types: ['authorization_code', 'refresh_token'],
    response_types: ['code'],
    token_endpoint_auth_method: 'none', // Public client (SPA)
  };

  try {
    const response = await fetch(`${BACKEND_URL}/auth/register`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(clientData),
    });

    if (!response.ok) {
      const error = await response.text();
      throw new Error(`Failed to register client: ${error}`);
    }

    const result = await response.json();
    
    console.log('✅ Client registered successfully!');
    console.log('');
    console.log('Client details:');
    console.log('================');
    console.log(`Client ID: ${result.client_id}`);
    console.log(`Client Name: ${result.client_name}`);
    console.log('');
    console.log('📝 Next steps:');
    console.log('1. Update src/config/oidc.config.ts with the client_id:');
    console.log(`   client_id: '${result.client_id}',`);
    console.log('');
    console.log('2. Create a .env file in the web project root:');
    console.log(`   VITE_BACKEND_URL=${BACKEND_URL}`);
    console.log('');
    console.log('3. Start the development server:');
    console.log('   pnpm dev');
    
  } catch (error) {
    console.error('❌ Failed to register client:', error.message);
    process.exit(1);
  }
}

// Run the registration
registerClient();
