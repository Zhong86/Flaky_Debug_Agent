import hashlib
import hmac


def sign_github_payload(secret: str, body: bytes) -> str:
    """The `X-Hub-Signature-256` value GitHub sends for *body*."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Check GitHub's HMAC-SHA256 signature over the raw request body, timing-safe."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    return hmac.compare_digest(signature_header, sign_github_payload(secret, body))
