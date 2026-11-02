from urllib.parse import urlsplit


def is_safe_redirect(target: str | None) -> bool:
    """Allow only same-site relative paths (prevents open-redirect attacks).

    Rejects absolute URLs ("https://evil.com"), scheme-relative ("//evil.com")
    and backslash tricks ("/\\evil.com") that some browsers normalise to "//".
    """
    if not target or not target.startswith("/"):
        return False
    if target.startswith("//") or "\\" in target:
        return False
    parts = urlsplit(target)
    return not parts.scheme and not parts.netloc
