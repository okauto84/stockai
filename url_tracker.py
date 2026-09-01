import base64
import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

DEFAULT_SECRET = "aistock-default-secret"
TRACKING_FILE = Path(__file__).parent / "data" / "url_tracking.jsonl"
_lock = threading.Lock()


def _get_key() -> bytes:
    secret = os.getenv("STOCKAI_TRACK_SECRET", DEFAULT_SECRET)
    return hashlib.sha256(secret.encode()).digest()


def encrypt(plain: str) -> str:
    """XOR + URL-safe Base64 간단 암호화"""
    key = _get_key()
    data = plain.encode("utf-8")
    encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return base64.urlsafe_b64encode(encrypted).decode().rstrip("=")


def decrypt(token: str) -> str:
    """encrypt()로 생성된 토큰 복호화"""
    key = _get_key()
    padding = "=" * (-len(token) % 4)
    encrypted = base64.urlsafe_b64decode(token + padding)
    plain = bytes(b ^ key[i % len(key)] for i, b in enumerate(encrypted))
    return plain.decode("utf-8")


def create_tracking_token(path: str, **params) -> str:
    """URL 경로와 파라미터를 암호화 토큰으로 변환"""
    payload = {"path": path, "params": params}
    return encrypt(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


def decode_tracking_token(token: str) -> dict:
    """암호화 토큰에서 경로·파라미터 복원"""
    return json.loads(decrypt(token))


def build_tracking_url(base_url: str, path: str, **params) -> str:
    """트래킹 토큰이 포함된 URL 생성"""
    token = create_tracking_token(path, **params)
    parsed = urlparse(base_url)
    query = urlencode({"t": token})
    return urlunparse((parsed.scheme, parsed.netloc, "/go", "", query, ""))


def _ensure_data_dir() -> None:
    TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)


def track_visit(
    path: str,
    method: str = "GET",
    query_string: str = "",
    ip: str | None = None,
    user_agent: str | None = None,
    referer: str | None = None,
    extra: dict | None = None,
) -> dict:
    """방문 URL 정보를 암호화하여 기록"""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "path": path,
        "method": method,
        "query": query_string,
        "ip": ip,
        "user_agent": user_agent,
        "referer": referer,
        **(extra or {}),
    }

    plain = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    entry = {
        "id": encrypt(f"{record['ts']}:{path}"),
        "data": encrypt(plain),
    }

    _ensure_data_dir()
    with _lock:
        with open(TRACKING_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return record


def read_tracking_logs(limit: int = 100) -> list[dict]:
    """저장된 트래킹 로그 복호화 조회"""
    if not TRACKING_FILE.exists():
        return []

    entries = []
    with open(TRACKING_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                entries.append({
                    "id": entry["id"],
                    "record": json.loads(decrypt(entry["data"])),
                })
            except (json.JSONDecodeError, ValueError, KeyError):
                continue

    return entries[-limit:]
