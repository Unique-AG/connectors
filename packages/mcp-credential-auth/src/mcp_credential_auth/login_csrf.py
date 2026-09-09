import hashlib
import hmac
import secrets
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import Response


@dataclass(frozen=True)
class LoginCsrf:
    cookie_prefix: str
    token_bytes: int = 32
    name_digest_chars: int = 16

    def cookie_name(self, request_id: str) -> str:
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()[: self.name_digest_chars]
        return f"{self.cookie_prefix}{digest}"

    def issue_token(self) -> str:
        return secrets.token_urlsafe(self.token_bytes)

    def set_cookie(
        self,
        response: Response,
        request_id: str,
        token: str,
        *,
        path: str,
        max_age_seconds: int,
        secure: bool,
    ) -> None:
        response.set_cookie(
            self.cookie_name(request_id),
            token,
            max_age=max_age_seconds,
            path=path,
            httponly=True,
            secure=secure,
            samesite="lax",
        )

    def clear_cookie(
        self,
        response: Response,
        request_id: str,
        *,
        path: str,
        secure: bool,
    ) -> None:
        response.delete_cookie(
            self.cookie_name(request_id),
            path=path,
            secure=secure,
            httponly=True,
            samesite="lax",
        )

    def token_is_valid(self, request: Request, request_id: str, submitted: str) -> bool:
        cookie = request.cookies.get(self.cookie_name(request_id))
        if not cookie or not submitted:
            return False
        return hmac.compare_digest(cookie, submitted)
