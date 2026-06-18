"""Password verification and hashing for usuarios."""
import hashlib
import hmac

try:
    import bcrypt
except ImportError:  # fallback para ambientes sem dependencia instalada
    bcrypt = None


def password_is_bcrypt(stored: str) -> bool:
    return isinstance(stored, str) and stored.startswith("$2")


def verify_password(stored, plain: str) -> bool:
    if plain is None or stored is None:
        return False
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8", errors="replace")
    if password_is_bcrypt(stored):
        if bcrypt is None:
            return False
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except Exception:
            return False
    if isinstance(stored, str) and stored.startswith("sha256$"):
        candidate = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return hmac.compare_digest(stored, "sha256$" + candidate)
    return stored == plain


def hash_password(plain: str) -> str:
    if bcrypt is None:
        digest = hashlib.sha256(plain.encode("utf-8")).hexdigest()
        return "sha256$" + digest
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
