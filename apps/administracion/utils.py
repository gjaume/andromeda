import re
import unicodedata


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos y con los espacios colapsados: para comparar textos."""
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_acentos).strip().lower()
