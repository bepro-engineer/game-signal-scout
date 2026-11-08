import hashlib


def source_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]
