#!/usr/bin/env python3

"""
Simple OAuth test script to trigger Google authentication.
This will open a browser and create the token.json file.
"""

import os
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Scopes for both Calendar and Docs
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/documents',
    'https://www.googleapis.com/auth/drive.file'
]

def main():
    print("🔐 Starting Google OAuth authentication...")
    print("📋 Scopes requested:")
    for scope in SCOPES:
        print(f"   - {scope}")
    print()
    
    # Check if credentials.json exists
    credentials_path = 'credentials.json'
    if not Path(credentials_path).exists():
        print(f"❌ Error: {credentials_path} not found!")
        print("Please make sure credentials.json is in the current directory.")
        return
    
    print(f"✅ Found {credentials_path}")
    
    # Check if token.json already exists
    token_path = Path('token.json')
    if token_path.exists():
        print("⚠️  token.json already exists!")
        print("If you want to re-authenticate, delete token.json first.")
        return
    
    print("🚀 Starting OAuth flow...")
    print("📱 A browser window will open for authentication.")
    print()
    
    try:
        # Create the flow
        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
        
        # Run the OAuth flow (this will open a browser)
        creds = flow.run_local_server(port=0)
        
        # Save the credentials
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✅ Authentication successful!")
        print("📄 token.json created with the following scopes:")
        print(f"   - {creds.scopes}")
        print()
        print("🎉 You can now start the server!")
        
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        print("Please check your credentials.json file and try again.")

if __name__ == "__main__":
    main()
