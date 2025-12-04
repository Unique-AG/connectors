#!/usr/bin/env node

/**
 * Script to register the web client with the OAuth server
 * Run this once after starting the backend server
 */

const BACKEND_URL = process.env.BACKEND_URL || 'http://localhost:3000';
const FRONTEND_URL = process.env.FRONTEND_URL || 'http://localhost:8080';

async function registerClient() {
  const clientData = {
    client_name: 'Agentic Outlook MCP Web',
    client_description: 'Web interface for Agentic Outlook MCP',
    redirect_uris: [`${FRONTEND_URL}/callback`, 'http://localhost:8080/callback'],
    grant_types: ['authorization_code', 'refresh_token'],
    response_types: ['code'],
    token_endpoint_auth_method: 'none',
  };

  try {
    const response = await fetch(`${BACKEND_URL}/oauth/register`, {
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
    console.log('1. Update the .env file with the client_id:');
    console.log(`   VITE_OAUTH_CLIENT_ID=${result.client_id}`);
    console.log('');
    console.log('2. Start the development server:');
    console.log('   pnpm dev');
  } catch (error) {
    console.error('❌ Failed to register client:', error.message);
    process.exit(1);
  }
}

// Run the registration
registerClient();
