"""Minimal client for Bolagsverket's free "API för värdefulla datamängder" (HVD).

Facts (Bolagsverket pages + working third-party clients, 2026):
  * Credentials: free "Kundanmälan" form on bolagsverket.se. client_id/client_secret for
    the test and production environments arrive by e-mail and SMS.
  * OAuth2 client-credentials, scope "vardefulla-datamangder:read".
  * POST {API_BASE}/organisationer  {"identitetsbeteckning": "<orgnr>"}  -> JSON.
  * Limit: 60 requests per minute per user. We stay below with MIN_INTERVAL_S.
Token URL and API base are configurable because public sources disagree on the token host;
confirm both on Bolagsverket's developer portal before the first run.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field

from .config import Config

MIN_INTERVAL_S = 1.1  # 60 requests/minute limit -> ~54/minute
USER_AGENT = "nyabolag/0.2 (reklamsparr verification)"


class HvdError(RuntimeError):
    pass


@dataclass
class HvdClient:
    cfg: Config
    _token: str | None = None
    _last_call: float = 0.0
    calls: int = field(default=0)

    def _post(self, url: str, data: bytes, headers: dict) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def token(self) -> str:
        if not (self.cfg.hvd_client_id and self.cfg.hvd_client_secret):
            raise HvdError("HVD_CLIENT_ID / HVD_CLIENT_SECRET are not set")
        basic = base64.b64encode(f"{self.cfg.hvd_client_id}:{self.cfg.hvd_client_secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": self.cfg.hvd_scope}).encode()
        status, raw = self._post(self.cfg.hvd_token_url, body, {
            "Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"})
        if status != 200:
            raise HvdError(f"token request failed: HTTP {status}")  # never log the response body (may echo secrets)
        self._token = json.loads(raw)["access_token"]
        return self._token

    def organisation(self, orgnr: str) -> tuple[int, dict]:
        """Look up one organisation. Returns (http_status, json body or {})."""
        if self._token is None:
            self.token()
        for attempt in range(4):
            wait = MIN_INTERVAL_S - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
            status, raw = self._post(
                f"{self.cfg.hvd_api_base.rstrip('/')}/organisationer",
                json.dumps({"identitetsbeteckning": orgnr}).encode(),
                {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json",
                 "Accept": "application/json", "X-Request-Id": str(uuid.uuid4())})
            if status == 401 and attempt == 0:
                self.token()
                continue
            if status in (429, 500, 502, 503, 504):
                time.sleep(5 * (attempt + 1))
                continue
            try:
                return status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return status, {}
        return status, {}
