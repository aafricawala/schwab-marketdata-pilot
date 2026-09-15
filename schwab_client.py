import requests
import urllib.parse

AUTH_URL = "https://api.schwabapi.com/v1/oauth/authorize"
TOKEN_URL = "https://api.schwabapi.com/v1/oauth/token"
MARKETDATA_BASE = "https://api.schwabapi.com/marketdata/v1"

class SchwabClient:
    def __init__(self, client_id, redirect_uri):
        self.client_id = client_id
        self.redirect_uri = redirect_uri
        self.access_token = None

    def build_auth_url(self):
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": "api"
        }
        return AUTH_URL + "?" + urllib.parse.urlencode(params)

    def exchange_code_for_token(self, code, client_secret):
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": client_secret
        }
        resp = requests.post(TOKEN_URL, data=data)
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]
        return resp.json()

    def get_quote(self, symbol):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"{MARKETDATA_BASE}/quotes/{symbol}"
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()
