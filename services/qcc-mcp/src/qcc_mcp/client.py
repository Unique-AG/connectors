"""QCC KYC/KYB gateway client — the transport layer for the MCP tools.

Ported from the qcc-connector-skill's proven `qcc.py`: stdlib `urllib`, the
three-header signature auth, and the async submit→poll flow. Synchronous by
design; the tools call it via `asyncio.to_thread` so a poll's sleeps never
block the event loop.

Auth: every call carries `ApiKey`, `Timespan` (unix seconds), and
`Token = MD5(ApiKey + Timespan + SecretKey)` uppercased. The SecretKey is never
transmitted.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from qcc_mcp.config import QccConfig

_OK = "200"          # valid, data present
_NO_RESULTS = "201"  # valid, empty result set
_PROCESSING = "204"  # async report not ready yet -> keep polling

# Granular sections of a submitted order. The bool marks paginated endpoints
# (shareholders/officers) that take `pageIndex`. Object sections return under
# `result`; list sections under `resultList`.
SECTIONS: dict[str, tuple[str, bool]] = {
    "profile": ("/corp/getCompanyProfile", False),
    "capital": ("/corp/getShareCapital", False),
    "shareholders": ("/corp/listShareholders", True),
    "officers": ("/corp/listOfficers", True),
    "branches": ("/corp/getBranchList", False),
    "subsidiaries": ("/corp/listSubsidiaries", False),
    "affiliates": ("/corp/listAffiliates", False),
    "ubo": ("/corp/getUBO", False),
}


class QccError(RuntimeError):
    """A QCC gateway call returned a non-success body status."""


class QccClient:
    def __init__(self, config: QccConfig) -> None:
        self._key = config.api_key.get_secret_value()
        self._secret = config.secret_key.get_secret_value()
        self._base = config.base_url.rstrip("/")
        self._timeout = config.timeout_s

    def _headers(self) -> dict[str, str]:
        ts = str(int(time.time()))
        token = hashlib.md5(f"{self._key}{ts}{self._secret}".encode()).hexdigest().upper()
        return {"ApiKey": self._key, "Timespan": ts, "Token": token}

    def _call(self, method: str, path: str,
              params: dict[str, str] | None = None,
              body: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self._base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            raise QccError(f"{path}: HTTP {exc.code}") from exc
        status = payload.get("status")
        if status not in (_OK, _NO_RESULTS, _PROCESSING):
            raise QccError(f"{path}: status={status} msg={payload.get('msg')}")
        return payload

    # 1. resolve
    def search(self, term: str, region: str = "CN") -> list[dict[str, Any]]:
        return self._call("GET", "/open/corp/search",
                          params={"searchTerm": term, "regionCode": region}).get("resultList") or []

    def search_person(self, term: str, corp_name: str) -> list[dict[str, Any]]:
        return self._call("GET", "/open/pers/search",
                          params={"searchTerm": term, "corpName": corp_name}).get("resultList") or []

    def resolve_one(self, term: str, region: str = "CN") -> str:
        hits = self.search(term, region)
        if not hits:
            raise QccError(f"No entity matched {term!r} in {region}.")
        return hits[0]["qccCode"]

    # 2. order + 3. poll
    def submit_order(self, submit_path: str, ref: dict[str, str]) -> str:
        return self._call("POST", submit_path, body=ref)["result"]["orderNo"]

    def poll_result(self, get_path: str, order_no: str,
                    interval: int = 10, tries: int = 18) -> dict[str, Any]:
        for _ in range(tries):
            body = self._call("GET", get_path, params={"orderNo": order_no})
            if body.get("status") == _OK and body.get("result"):
                return body["result"]
            time.sleep(interval)
        raise QccError(f"{get_path}: report {order_no} not ready after {tries} polls")

    def get_section(self, section: str, order_no: str, page: int | None = None,
                    interval: int = 10, tries: int = 18) -> Any:
        try:
            path, paginated = SECTIONS[section]
        except KeyError:
            raise QccError(f"unknown section {section!r}; choose from {', '.join(SECTIONS)}") from None
        params = {"orderNo": order_no}
        if paginated and page is not None:
            params["pageIndex"] = str(page)
        for _ in range(tries):
            body = self._call("GET", path, params=params)
            if body.get("status") != _PROCESSING:
                result = body.get("result")
                return result if result is not None else (body.get("resultList") or [])
            time.sleep(interval)
        raise QccError(f"{path}: section {section} of {order_no} not ready after {tries} polls")

    # convenience: full report in one call
    def kyc_basic(self, term: str, region: str = "CN") -> dict[str, Any]:
        return self.poll_result("/corp/getBasic",
                                self.submit_order("/corp/submitKYCBasicOrder",
                                                  {"qccCode": self.resolve_one(term, region)}))

    def kyc_ubo(self, term: str, region: str = "CN") -> dict[str, Any]:
        return self.poll_result("/corp/getUBO",
                                self.submit_order("/corp/submitKYCUBOOrder",
                                                  {"qccCode": self.resolve_one(term, region)}))

    def kyc_executive(self, name: str, corp_name: str) -> dict[str, Any]:
        hits = self.search_person(name, corp_name)
        if not hits:
            raise QccError(f"No person matched {name!r} at {corp_name!r}.")
        return self.poll_result("/pers/getExecutive",
                                self.submit_order("/pers/submitKYCExecutiveOrder",
                                                  {"personKeyNo": hits[0]["personKeyNo"]}))

    def submit_ubo(self, term: str, region: str = "CN") -> str:
        return self.submit_order("/corp/submitKYCUBOOrder", {"qccCode": self.resolve_one(term, region)})
