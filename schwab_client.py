"""
schwab_client.py

This file defines the SchwabClient class, which handles:
1. Building the OAuth authorization URL.
2. Exchanging the authorization code for an access token.
3. Making authenticated requests to Schwab's Market Data API.

IMPORTANT:
- This file NEVER stores your Schwab Client ID, Client Secret, or tokens.
- All sensitive values must be passed in from your Colab notebook using
  environment variables.
- This file is safe to commit to GitHub.
"""

# Import the 'requests' library to make HTTP calls to Schwab's API.
import requests

# Import urllib.parse to safely encode URL parameters.
import urllib.parse

# Define the Schwab OAuth authorization endpoint.
# This is where the user logs in and approves access.
AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"

# Define the Schwab OAuth token endpoint.
# This is where your app exchanges the authorization code for an access token.
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"

# Define the base URL for Schwab's Market Data API.
# All quote endpoints are built from this base.
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"


class SchwabClient:
    """
    The SchwabClient class encapsulates all logic needed to:
    - Build OAuth URLs
    - Exchange authorization codes
    - Make authenticated market data requests
    """

    def __init__(self, client_id, redirect_uri):
        """
        Initialize the SchwabClient with:
        - client_id: Your Schwab App Key (Client ID)
        - redirect_uri: The Callback URL registered in your Schwab Developer App

        The access_token is set to None initially and will be populated
        after the OAuth token exchange.
        """

        # Store the Client ID provided by the user.
        self.client_id = client_id

        # Store the Redirect URI provided by the user.
        self.redirect_uri = redirect_uri

        # Initialize the access token as None until OAuth completes.
        self.access_token = None


    def build_auth_url(self):
        """
        Build the OAuth authorization URL that the user must open in a browser.

        This URL includes:
        - response_type=code (OAuth standard)
        - client_id (your app's identifier)
        - redirect_uri (must match Schwab's configuration)
        - scope=api (required for Market Data access)

        The user logs in at this URL and approves access.
        Schwab then redirects to your redirect_uri with a ?code= parameter.
        """

        # Define the URL parameters required for OAuth authorization.
        params = {
            "response_type": "code",      # OAuth requires "code" for authorization.
            "client_id": self.client_id,  # Your Schwab Client ID.
            "redirect_uri": self.redirect_uri,  # Must match Schwab's app settings.
            "scope": "api"                # Required scope for Market Data API.
        }

        # Encode the parameters and append them to the AUTH_URL.
        return AUTH_URL + "?" + urllib.parse.urlencode(params)


    def exchange_code_for_token(self, code, client_secret):
        """
        Exchange the authorization code for an access token.

        Parameters:
        - code: The authorization code returned by Schwab after login.
        - client_secret: Your Schwab App Secret (never stored in this file).

        This method:
        - Sends a POST request to Schwab's token endpoint.
        - Receives an access token.
        - Stores the access token in the client instance.
        """

        # Prepare the POST request payload required by Schwab's OAuth token endpoint.
        data = {
            "grant_type": "authorization_code",  # OAuth grant type.
            "code": code,                        # The authorization code from Schwab.
            "redirect_uri": self.redirect_uri,   # Must match Schwab's app settings.
            "client_id": self.client_id,         # Your Schwab Client ID.
            "client_secret": client_secret       # Your Schwab Client Secret.
        }

        # Send the POST request to Schwab's token endpoint.
        resp = requests.post(TOKEN_URL, data=data)

        # Raise an exception if the request failed (e.g., invalid code).
        resp.raise_for_status()

        # Parse the JSON response containing the access token.
        token_data = resp.json()

        # Store the access token in the client instance for future API calls.
        self.access_token = token_data["access_token"]

        # Return the full token response for debugging or inspection.
        return token_data


    def get_quote(self, symbol):
        """
        Retrieve a market quote for a given symbol using Schwab's Market Data API.

        Parameters:
        - symbol: A string representing the ticker symbol (e.g., "AAPL").

        This method:
        - Ensures an access token is available.
        - Sends a GET request to the quotes endpoint.
        - Returns the JSON response containing market data.
        """

        # Ensure that an access token has been obtained before making API calls.
        if not self.access_token:
            raise RuntimeError("No access token available. Run OAuth flow first.")

        # Define the Authorization header using the Bearer token.
        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

        # Construct the full URL for the quote endpoint.
        url = f"{MARKETDATA_BASE}/quotes/{symbol}"

        # Send the GET request to Schwab's Market Data API.
        resp = requests.get(url, headers=headers)

        # Raise an exception if the request failed.
        resp.raise_for_status()

        # Return the JSON response containing the quote data.
        return resp.json()
