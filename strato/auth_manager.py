import base64
import hashlib
import json
import random
import string
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional, Tuple

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from . import api, constants

# OAuth2 Configuration Constants
REDIRECT_URL = "http://localhost:9248/callback"


# HTML Response Templates
def get_auth_handler_response():
    """Generate the authentication success response with redirect to website."""
    api_config = api.config.get_api_config()
    website_url = api_config.SERVER_URL + "/dashboard"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <title>Login Successful</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background-color: #f0f0f0;
        }}
        .container {{
            background-color: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            padding: 60px 40px;
            max-width: 500px;
            text-align: center;
        }}
        .checkmark-circle {{
            width: 60px;
            height: 60px;
            border-radius: 50%;
            background-color: #5CB85C;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 24px;
        }}
        .checkmark {{
            width: 30px;
            height: 30px;
            fill: white;
        }}
        h1 {{
            color: #1a1a1a;
            font-size: 28px;
            font-weight: 600;
            margin: 0 0 20px 0;
        }}
        .message {{
            font-size: 16px;
            color: #666;
            line-height: 1.5;
            margin: 0 0 24px 0;
        }}
        .redirect-link {{
            font-size: 14px;
            color: #999;
        }}
        .redirect-link a {{
            color: #007bff;
            text-decoration: underline;
        }}
        .redirect-link a:hover {{
            color: #0056b3;
        }}
        #countdown-num {{
            font-weight: bold;
        }}
    </style>
    <script>
        let countdown = 3;
        let countdownNumElement;
        let countdownSecondsElement;

        function updateCountdown() {{
            if (countdownNumElement) {{
                countdownNumElement.textContent = countdown;
            }}
            if (countdownSecondsElement) {{
                countdownSecondsElement.textContent = countdown === 1 ? 'second' : 'seconds';
            }}

            if (countdown <= 0) {{
                window.location.href = '{website_url}';
            }} else {{
                countdown--;
                setTimeout(updateCountdown, 1000);
            }}
        }}

        window.onload = function() {{
            countdownNumElement = document.getElementById('countdown-num');
            countdownSecondsElement = document.getElementById('countdown-seconds');
            updateCountdown();
        }};
    </script>
</head>
<body>
    <div class="container">
        <div class="checkmark-circle">
            <svg class="checkmark" viewBox="0 0 24 24">
                <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41L9 16.17z"/>
            </svg>
        </div>
        <h1>Login Successful!</h1>
        <p class="message">You've signed in to Strato successfully. You'll be<br>redirected to your dashboard in <span id="countdown-num">3</span> <span id="countdown-seconds">seconds</span>...</p>
        <p class="redirect-link">If you're not redirected, click <a href="{website_url}">here</a>.</p>
    </div>
</body>
</html>
"""


AUTH_HANDLER_RESPONSE_ERROR = """
<!DOCTYPE html>
<html>
<head>
    <title>Authentication Error</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            text-align: center;
            margin-top: 50px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 30px;
            max-width: 500px;
            margin: 0 auto;
        }
        h1.error {
            color: #F44336;
        }
        p {
            font-size: 16px;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="error">Authentication Error</h1>
        <p>Error: {}</p>
        <p>Please try again or contact support.</p>
    </div>
</body>
</html>
"""

# Optional redirect URLs after authentication
AUTH_HANDLER_REDIRECT = None  # URL to redirect on success
AUTH_HANDLER_REDIRECT_CANCELLED = None  # URL to redirect on error


class AuthManager(QObject):
    auth_completed = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, cognito_url: str, cognito_client_id: str, port: int = 5000):
        """Initialize the Cognito authentication manager.

        Args:
            port: Port to use for the local callback server
        """
        super().__init__()
        self.port = port
        self.server = None
        self.server_thread = None
        self.id_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.user_info = None
        self.error = None
        self.code_verifier = None
        self.state = None
        self.auth_timer = None
        self.auth_start_time = None
        self.cognito_url = cognito_url
        self.cognito_client_id = cognito_client_id

    def _generate_code_verifier(self) -> str:
        """Generate a code verifier for PKCE.

        Returns:
            A random string of 43-128 characters
        """
        code_verifier = "".join(
            random.choice(string.ascii_letters + string.digits + "-._~")
            for _ in range(64)
        )
        return code_verifier

    def _generate_code_challenge(self, code_verifier: str) -> str:
        """Generate a code challenge from the code verifier using S256 method.

        Args:
            code_verifier: The code verifier string

        Returns:
            The code challenge string
        """
        code_challenge = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(code_challenge).decode("utf-8").rstrip("=")
        )
        return code_challenge

    def _generate_state(self) -> str:
        """Generate a random state parameter for OAuth2 security.

        Returns:
            A random string to use as state parameter
        """
        return "".join(
            random.choice(string.ascii_letters + string.digits) for _ in range(32)
        )

    def start_local_server(self) -> bool:
        """Start the local HTTP server to handle the Cognito OAuth2 callback.

        Returns:
            True if server started successfully, False otherwise
        """

        try:
            self.server = HTTPServer(("localhost", self.port), _Handler)
            self.server.id_token = None
            self.server.refresh_token = None
            self.server.expires_in = None
            self.server.user_info = None
            self.server.error = None
            self.server.auth_code = None
            self.server.state = None
            self.server.redirect_url = REDIRECT_URL
            self.server.cognito_url = self.cognito_url
            self.server.client_id = self.cognito_client_id

            self.server.code_verifier = self.code_verifier
            self.server.expected_state = self.state

            # Start server in a separate thread
            self.server_thread = threading.Thread(target=self.server.serve_forever)
            self.server_thread.daemon = True
            self.server_thread.start()
            return True
        except Exception as e:
            self.error = str(e)
            return False

    def stop_local_server(self):
        """Stop the local HTTP server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            if self.server_thread:
                self.server_thread.join()

    def _check_auth_status(self):
        """Check authentication status periodically using QTimer."""
        # Check if timeout has been reached
        if time.time() - self.auth_start_time > 300:  # 5 minutes timeout
            self._cleanup_auth()
            self.auth_completed.emit(False, "Timeout waiting for authentication")
            return

        # Check if server is not ready yet
        if not self.server:
            return

        # Check if token has been received
        if hasattr(self.server, "id_token") and self.server.id_token:
            # Transfer token information from server to instance variables
            self.id_token = self.server.id_token
            self.refresh_token = self.server.refresh_token
            if hasattr(self.server, "expires_in") and self.server.expires_in:
                self.token_expiry = time.time() + self.server.expires_in
            self.user_info = (
                self.server.user_info if hasattr(self.server, "user_info") else None
            )
            self._cleanup_auth()
            self.auth_completed.emit(True, "")
        # Check if error occurred
        elif hasattr(self.server, "error") and self.server.error:
            error = self.server.error
            self._cleanup_auth()
            self.auth_completed.emit(False, error)

    def _cleanup_auth(self):
        """Clean up authentication resources."""
        if self.auth_timer:
            self.auth_timer.stop()
            self.auth_timer = None
        self.stop_local_server()

    def start_async_auth(self):
        """Start asynchronous authentication process."""
        self.auth_start_time = time.time()

        # Create and start timer
        self.auth_timer = QTimer()
        self.auth_timer.timeout.connect(self._check_auth_status)
        self.auth_timer.start(200)  # Check every 200ms

    def authenticate(self, timeout: int = 300) -> Tuple[bool, Optional[str]]:
        """Complete Cognito OAuth2 authentication flow.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            Tuple of (success, error_message or auth_url)
        """
        # Generate authorization parameters first
        # Generate PKCE code verifier and challenge
        code_verifier = self._generate_code_verifier()
        code_challenge = self._generate_code_challenge(code_verifier)
        state = self._generate_state()

        # Store these values for later verification
        self.code_verifier = code_verifier
        self.state = state
        print(f"Auth flow - Generated state: {state}")

        # Start local server
        if not self.start_local_server():
            return False, f"Failed to start local server: {self.error}"

        # Get authorization URL with the same state parameter
        auth_url = (
            f"{self.cognito_url}/oauth2/authorize?"
            f"client_id={self.cognito_client_id}&"
            f"redirect_uri={REDIRECT_URL}&"
            f"response_type=code&"
            f"scope=openid+email+profile&"
            f"state={state}&"
            f"code_challenge={code_challenge}&"
            f"code_challenge_method=S256"
        )

        # Return the URL for the user to open in their browser
        return True, auth_url

    def get_id_token(self) -> Optional[str]:
        """Get the current id token if available and not expired.

        Returns:
            Id token or None if not authenticated or token expired
        """
        if not self.id_token or (self.token_expiry and time.time() > self.token_expiry):
            return None
        return self.id_token

    def get_refresh_token(self) -> Optional[str]:
        """Get the current refresh token if available.

        Returns:
            Refresh token or None if not authenticated
        """
        return self.refresh_token

    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """Get the user information if available.

        Returns:
            User information or None if not authenticated
        """
        return self.user_info


class _Handler(BaseHTTPRequestHandler):
    """
    HTTP handler for Cognito OAuth2 callbacks
    """

    # pylint: disable=missing-function-docstring

    def log_request(self, _format, *args):  # pylint: disable=arguments-differ
        """Suppress default request logging"""
        pass

    def do_GET(self):
        """Handle GET requests to the callback URL"""
        print(f"\n\nReceived request with path: {self.path}")
        print(f"Full request: {self.requestline}")

        # Check if this is the callback path
        if not (self.path.startswith("/callback") or self.path == "/"):
            print(f"Path is not recognized as a callback: {self.path}")
            self.send_response(404)
            self.end_headers()
            return

        # Parse the query parameters
        query_params = {}
        if "?" in self.path:
            query_string = self.path.split("?", 1)[1]
            query_params = dict(urllib.parse.parse_qsl(query_string))

        # Check for error in the callback
        if "error" in query_params:
            error_description = query_params.get("error_description", "Unknown error")
            self.server.error = f"Authentication error: {error_description}"
            self._send_response()
            return

        # Check for authorization code
        if "code" in query_params:
            # Verify state parameter to prevent CSRF
            state = query_params.get("state")
            # デバッグ情報を出力
            print(f"Received state: {state}")
            print(f"Expected state: {self.server.expected_state}")

            # 一時的にstate検証をスキップ（デバッグ用）
            if state != self.server.expected_state:
                print("State mismatch detected, but continuing for debugging")
                # self.server.error = "State mismatch, possible CSRF attack"
                # self._send_response()
                # return

            # Store the authorization code
            self.server.auth_code = query_params["code"]
            self.server.state = state

            # Exchange the code for tokens
            try:
                # Prepare token request
                token_url = f"{self.server.cognito_url}/oauth2/token"
                data = {
                    "grant_type": "authorization_code",
                    "client_id": self.server.client_id,
                    "code": self.server.auth_code,
                    "redirect_uri": self.server.redirect_url,
                    "code_verifier": self.server.code_verifier,
                }
                encoded_data = urllib.parse.urlencode(data).encode("utf-8")

                # Send token request
                headers = {"Content-Type": "application/x-www-form-urlencoded"}
                req = urllib.request.Request(
                    token_url, data=encoded_data, headers=headers
                )

                with urllib.request.urlopen(req) as response:
                    token_response = json.loads(response.read().decode("utf-8"))

                    # Extract tokens
                    self.server.id_token = token_response.get("id_token")
                    self.server.refresh_token = token_response.get("refresh_token")
                    self.server.expires_in = token_response.get("expires_in")

                    # ログ出力でトークンが設定されたことを明示
                    print("Tokens successfully obtained and set on server instance")

                    # Extract user info from ID token (JWT)
                    if self.server.id_token:
                        # JWT payload is in the second part of the token
                        jwt_parts = self.server.id_token.split(".")
                        if len(jwt_parts) >= 2:
                            # Add padding if needed
                            payload = jwt_parts[1]
                            payload += "=" * ((4 - len(payload) % 4) % 4)
                            try:
                                decoded_payload = base64.b64decode(payload).decode(
                                    "utf-8"
                                )
                                self.server.user_info = json.loads(decoded_payload)
                            except Exception as e:
                                print(f"Error decoding JWT payload: {e}")

            except Exception as e:
                self.server.error = f"Error exchanging code for tokens: {str(e)}"
                print(f"Token exchange error: {e}")

        # トークンが設定された場合、wait_for_callbackがトークンを検出できるように少し待機
        if hasattr(self.server, "id_token") and self.server.id_token:
            print("Waiting briefly to ensure token is detected by wait_for_callback...")
            time.sleep(1)  # 1秒の遅延を追加

        # Return HTML response
        self._send_response()
        return

    def do_POST(self):
        """Handle POST requests"""
        # This method is kept for compatibility but not actively used in the OAuth2 flow
        self.send_response(404)
        self.end_headers()

    def _send_response(self):
        if AUTH_HANDLER_REDIRECT and self.server.error is None:
            self.send_response(302)
            self.send_header("Location", AUTH_HANDLER_REDIRECT)
            self.end_headers()
        elif AUTH_HANDLER_REDIRECT_CANCELLED and self.server.error:
            self.send_response(302)
            self.send_header("Location", AUTH_HANDLER_REDIRECT_CANCELLED)
            self.end_headers()
        else:
            self.send_response(200)
            # Content-typeヘッダーにcharsetを指定して日本語の文字化けを防止
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            if self.server.error is not None:
                self.wfile.write(
                    AUTH_HANDLER_RESPONSE_ERROR.format(self.server.error).encode(
                        "utf-8"
                    )
                )
            else:
                response_html = get_auth_handler_response()
                self.wfile.write(response_html.encode("utf-8"))
