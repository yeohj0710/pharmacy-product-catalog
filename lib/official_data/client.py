from __future__ import annotations

import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .sources import SourceSpec


class MissingServiceKey(RuntimeError):
    pass


class PublicApiError(RuntimeError):
    pass


class DataGoClient:
    def __init__(
        self,
        *,
        cache_dir: Path,
        service_key: str | None = None,
        requests_per_second: float = 1.5,
        timeout: float = 25.0,
        retries: int = 4,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        raw_key = service_key if service_key is not None else os.environ.get("DATA_GO_KR_SERVICE_KEY", "")
        self.service_key = urllib.parse.unquote(raw_key.strip())
        self.minimum_interval = 1.0 / max(requests_per_second, 0.1)
        self.timeout = timeout
        self.retries = retries
        self.last_request_at = 0.0
        self.api_calls = 0
        self.cache_hits = 0

    def cache_path(self, source: SourceSpec, params: dict[str, Any]) -> Path:
        stable = json.dumps(
            {"endpoint": source.endpoint, "params": {key: params[key] for key in sorted(params)}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(stable).hexdigest()
        return self.cache_dir / source.dataset_id / source.key / f"{digest}.json"

    def request_json(self, source: SourceSpec, params: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
        cache_path = self.cache_path(source, params)
        if cache_path.exists() and not force:
            self.cache_hits += 1
            return json.loads(cache_path.read_text(encoding="utf-8"))
        if not self.service_key:
            raise MissingServiceKey("DATA_GO_KR_SERVICE_KEY가 설정되지 않았습니다.")

        request_params = {
            "pageNo": 1,
            "numOfRows": 100,
            "type": "json",
            "returnType": "json",
            **params,
            source.key_name: self.service_key,
        }
        query = urllib.parse.urlencode(request_params, doseq=True)
        url = f"{source.endpoint}?{query}"
        payload: dict[str, Any] | None = None
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            wait = self.minimum_interval - (time.monotonic() - self.last_request_at)
            if wait > 0:
                time.sleep(wait)
            try:
                request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "pharmacy-product-catalog/1.0"})
                self.last_request_at = time.monotonic()
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8-sig")
                self.api_calls += 1
                payload = json.loads(raw)
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
                last_error = error
                retryable = not isinstance(error, urllib.error.HTTPError) or error.code == 429 or error.code >= 500
                if attempt >= self.retries or not retryable:
                    break
                time.sleep((2**attempt) + random.random())
        if payload is None:
            raise PublicApiError(f"{source.dataset_id} API 요청 실패: {type(last_error).__name__}") from last_error

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(cache_path)
        return payload
