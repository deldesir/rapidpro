import requests

# the bridge subscribes each of its users to the event types it should post; these are the two courier handles
EVENTS = ["Message", "ReadReceipt"]


class WuzapiError(Exception):
    """
    A call to the bridge failed - couldn't be made, or got a non-200 response
    """


class WuzapiClient:
    """
    Client for the bridge's HTTP API. Calls are authenticated by the per-user token the bridge issued when the user
    was created; creating a user needs the bridge's admin token instead.
    """

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token

    @classmethod
    def create_user(cls, base_url: str, admin_token: str, name: str, token: str):
        """
        Creates a bridge user with the given name and token, subscribed to the events courier handles
        """
        cls(base_url, admin_token)._request(
            "POST", "/admin/users", json={"name": name, "token": token, "events": ",".join(EVENTS)}
        )

    def set_webhook(self, url: str):
        self._request("POST", "/webhook", json={"webhookurl": url, "events": EVENTS})

    def set_hmac_key(self, key: str):
        self._request("POST", "/session/hmac/config", json={"hmac_key": key})

    def status(self) -> tuple[bool, bool]:
        """
        Returns whether the bridge is connected to WhatsApp for this user, and whether a phone is linked
        """
        data = self._request("GET", "/session/status").get("data", {})
        return _truthy(data.get("connected")), _truthy(data.get("loggedIn"))

    def connect(self):
        self._request("POST", "/session/connect", json={"Subscribe": EVENTS, "Immediate": True})

    def qr_code(self) -> str:
        """
        Returns the current QR code as a data URL, or an empty string if the bridge hasn't got one yet
        """
        return self._request("GET", "/session/qr").get("data", {}).get("QRCode") or ""

    def pair_phone(self, phone: str) -> str:
        """
        Asks WhatsApp to send a linking code to the given phone and returns it. Each call prompts the phone, so
        this is only ever called when the user asks for a code.
        """
        response = self._request("POST", "/session/pairphone", json={"Phone": phone}, timeout=30)
        return response.get("data", {}).get("LinkingCode") or response.get("LinkingCode") or ""

    def logout(self):
        self._request("POST", "/session/logout")

    def _request(self, method: str, path: str, *, json=None, timeout: int = 10) -> dict:
        try:
            response = requests.request(
                method, f"{self.base_url}{path}", json=json, headers={"Authorization": self.token}, timeout=timeout
            )
        except requests.RequestException as e:
            raise WuzapiError(f"unable to reach the bridge: {e}") from e

        if response.status_code != 200:
            raise WuzapiError(f"the bridge answered {response.status_code} to {method} {path}")

        try:
            return response.json()
        except ValueError as e:
            raise WuzapiError(f"the bridge answered {method} {path} with something other than JSON") from e


def _truthy(value) -> bool:
    return str(value).lower() in ("true", "1", "yes")
