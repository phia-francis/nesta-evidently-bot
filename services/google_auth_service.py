import json
import os
from collections.abc import Sequence

from google.oauth2 import service_account

from config import Config


def get_google_credentials(
    scopes: Sequence[str],
    *,
    require: bool = False,
    allow_file_fallback: bool = False,
) -> service_account.Credentials | None:
    json_str = Config.GOOGLE_SERVICE_ACCOUNT_JSON
    if json_str:
        info = json.loads(json_str)
        return service_account.Credentials.from_service_account_info(info, scopes=scopes)

    if allow_file_fallback and os.path.exists("service_account.json"):
        return service_account.Credentials.from_service_account_file("service_account.json", scopes=scopes)

    if require:
        raise ValueError("Missing GOOGLE_SERVICE_ACCOUNT_JSON in environment.")

    return None
