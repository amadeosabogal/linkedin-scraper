import sys
import os

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

try:
    print("Iniciando flujo de autenticación de Gmail...")
    flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
    creds = flow.run_local_server(port=0)
    
    with open('token.json', 'w') as token:
        token.write(creds.to_json())
        
    print("¡Autenticación exitosa! El archivo token.json ha sido creado.")
except Exception as e:
    print(f"Error de autenticación: {e}")
