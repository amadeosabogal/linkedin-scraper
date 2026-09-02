import os
import base64
from email.message import EmailMessage
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import logging

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        self.creds = None
        self.service = None
        self.base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self.token_path = os.path.join(self.base_dir, 'token.json')
        self.credentials_path = os.path.join(self.base_dir, 'credentials.json')

    def authenticate(self):
        """Authenticates using token.json or credentials.json"""
        if os.path.exists(self.token_path):
            self.creds = Credentials.from_authorized_user_file(self.token_path, SCOPES)
        
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    logger.error(f"Error refreshing token: {e}")
                    self.creds = None
            
            if not self.creds:
                if not os.path.exists(self.credentials_path):
                    raise Exception(f"Falta el archivo {self.credentials_path}. Por favor, configúralo en Google Cloud.")
                
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_path, SCOPES)
                # This will open a browser window for initial authentication
                self.creds = flow.run_local_server(port=0)
            
            # Save the credentials for the next run
            with open(self.token_path, 'w') as token:
                token.write(self.creds.to_json())

        self.service = build('gmail', 'v1', credentials=self.creds)

    def send_email(self, to_email: str, subject: str, body: str, is_html: bool = False):
        """Sends an email using the Gmail API."""
        if not self.service:
            self.authenticate()

        message = EmailMessage()
        
        if is_html:
            message.set_content(body, subtype='html')
        else:
            message.set_content(body)

        message['To'] = to_email
        message['From'] = 'me' # 'me' tells Gmail to use the authenticated user
        message['Subject'] = subject

        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'raw': encoded_message}

        try:
            send_message = (self.service.users().messages().send(
                userId="me", body=create_message).execute())
            logger.info(f"Message sent successfully: {send_message['id']}")
            return True, "Correo enviado exitosamente."
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False, f"Error al enviar el correo: {str(e)}"

# Singleton instance
email_service_instance = EmailService()
