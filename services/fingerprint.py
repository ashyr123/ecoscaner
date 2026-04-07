"""
fingerprint.py — EcoScaner duplicate detection engine

Değişiklikler:
  ✅ Color fingerprint'ten çıkarıldı
  ✅ Brand=UNKNOWN → volume da ignore edilir (bypass fix)
  ✅ is_visually_duplicate → d_threshold=10, a_threshold=12 (daha toleranslı)
  ✅ Hybrid dHash + aHash
  ✅ normalize_volume → 'n' birimi fix
"""

import hashlib
import io
import re
import logging
from collections import Counter

import imagehash
from PIL import Image

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# BÖLÜM 1 — Normalizasyon
# ─────────────────────────────────────────────────────────────

BRAND_SYNONYMS: dict[str, list[str]] = {
    "сочный":    ["сочный", "сочный витамин", "sochny", "sochniy", "сочныи", "sochni"],
    "добрый":    ["добрый", "dobry", "добрии", "dobriy"],
    "фруктовый": ["фруктовый", "fruktovy", "fruktoviy"],
    "любимый":   ["любимый", "lyubimiy", "lubimiy"],
    "goşa çynar": ["goşa çynar", "gosa cynar", "gosha chynar", "гоша чынар"],
}

_BRAND_LOOKUP: dict[str, str] = {}
for canonical, variants in BRAND_SYNONYMS.items():
    for v in variants:
        _BRAND_LOOKUP[v.strip().lower()] = canonical


def normalize_brand(brand: str) -> str:
    if not brand or brand.strip().upper() == "UNKNOWN":
        return "unknown"

    b = brand.strip().lower()

    # 1. Tam eşleşme
    if b in _BRAND_LOOKUP:
        return _BRAND_LOOKUP[b]

    # 2. İlk kelime eşleşmesi
    first_clean = re.sub(r"[^a-zа-яё0-9çşňäöü]", "", b.split()[0])
    if first_clean in _BRAND_LOOKUP:
        return _BRAND_LOOKUP[first_clean]

    # 3. Substring fuzzy — AI yeni varyant yazarsa yine yakala
    for variant, canonical in _BRAND_LOOKUP.items():
        if len(variant) >= 4 and (variant in b or b in variant):
            return canonical

    return first_clean or "unknown"


def normalize_volume(volume: str) -> str:
    if not volume or volume.strip().upper() == "UNKNOWN":
        return "any"
    raw    = volume.strip().lower()
    digits = re.sub(r"[^0-9.]", "", raw)
    if not digits:
        return "any"
    is_ml    = any(u in raw for u in ["ml", "мл"])
    is_litre = any(u in raw for u in ["l", "л", "n"]) and not is_ml
    if is_ml:
        return f"{digits}ml"
    elif is_litre:
        return f"{digits}l"
    elif "." in digits:
        return f"{digits}l"
    else:
        return f"{digits}ml"


# ─────────────────────────────────────────────────────────────
# BÖLÜM 2 — Composite Fingerprint
# ─────────────────────────────────────────────────────────────

def build_fingerprint(brand: str, volume: str, color: str = "") -> str:
    """
    SHA256(norm_brand | norm_volume)

    ⚠️ Brand=UNKNOWN ise volume da ignore edilir.
       Log'da görüldü: foto1=UNKNOWN|UNKNOWN, foto3=UNKNOWN|400ml
       → farklı fingerprint → bypass!
       Çözüm: brand unknown ise her zaman "unknown|any" kullan.

    ❌ color fingerprint'te yok — AI tutarsız döndürüyor.
    ❌ pHash fingerprint'te yok — is_visually_duplicate() ayrı kontrol eder.
    """
    nb = normalize_brand(brand)

    # Brand bilinmiyorsa volume da anlamsız — sabit "any" kullan
    if nb == "unknown":
        raw = "unknown|any"
    else:
        nv  = normalize_volume(volume)
        raw = f"{nb}|{nv}"

    result = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    logger.debug(
        "Fingerprint | brand='%s'→'%s' | raw='%s' | hash=%s...",
        brand, nb, raw, result[:12]
    )
    return result


# ─────────────────────────────────────────────────────────────
# BÖLÜM 3 — Perceptual Hash
# ─────────────────────────────────────────────────────────────

def get_perceptual_hash(image_bytes: bytes) -> str:
    """dHash + aHash hybrid. Format: 'dddd..._aaaa...'"""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    d   = str(imagehash.dhash(img))
    a   = str(imagehash.average_hash(img))
    return f"{d}_{a}"


def is_visually_duplicate(
    new_hash:      str,
    stored_hashes: list[str],
    d_threshold:   int = 10,  # ← 5'ten 10'a yükseltildi (farklı açılar geçiyordu)
    a_threshold:   int = 12,  # ← 8'den 12'ye yükseltildi
) -> bool:
    """
    dHash < d_threshold  VEYA  aHash < a_threshold → duplicate.

    Neden threshold yükseltildi?
    Aynı şişenin ön/arka/yan yüzü görsel olarak çok farklı.
    threshold=5 → Hamming mesafesi 5'i aşıyordu → bypass oluyordu.
    threshold=10/12 → farklı açıları da yakalar, yanlış pozitif riski kabul edilebilir.
    """
    if not stored_hashes:
        return False

    try:
        new_d, new_a = new_hash.split("_")
        new_dhash    = imagehash.hex_to_hash(new_d)
        new_ahash    = imagehash.hex_to_hash(new_a)
    except Exception as e:
        logger.warning("pHash parse hatası: %s", e)
        return False

    for stored in stored_hashes:
        try:
            stored_d, stored_a = stored.split("_")
            d_dist = new_dhash - imagehash.hex_to_hash(stored_d)
            a_dist = new_ahash - imagehash.hex_to_hash(stored_a)

            if d_dist < d_threshold or a_dist < a_threshold:
                logger.info(
                    "Görsel duplicate | dHash=%d (eşik=%d) | aHash=%d (eşik=%d)",
                    d_dist, d_threshold, a_dist, a_threshold
                )
                return True
        except Exception as e:
            logger.warning("pHash karşılaştırma hatası: %s", e)
            continue

    return False


# ─────────────────────────────────────────────────────────────
# BÖLÜM 4 — ProductAnalyzer
# ─────────────────────────────────────────────────────────────

class ProductAnalyzer:
    def __init__(self):
        self._results: list[dict] = []

    def add(self, result: dict) -> None:
        if result and not isinstance(result, Exception):
            self._results.append(result)

    def fuse(self) -> dict:
        if not self._results:
            return {}
        if len(self._results) == 1:
            return self._results[0]

        def majority(field: str, fallback: str = "UNKNOWN") -> str:
            values = [
                r[field] for r in self._results
                if r.get(field) and str(r[field]).strip().upper() != "UNKNOWN"
            ]
            if not values:
                return fallback
            return Counter(values).most_common(1)[0][0]

        n           = len(self._results)
        best_conf   = max(self._results, key=lambda r: r.get("confidence", 0))
        empty_votes = sum(1 for r in self._results if r.get("is_empty", True))  # default True
        avg_conf    = sum(r.get("confidence", 0) for r in self._results) // n

        fused = {
            "category":      majority("category"),
            "brand":         majority("brand"),
            "volume":        best_conf.get("volume", "UNKNOWN"),
            "color":         majority("color"),
            "is_empty":      empty_votes >= n / 2,   # ← > → >= : tie durumunda boş varsay
            "confidence":    avg_conf,
            "is_recyclable": all(r.get("is_recyclable", True) for r in self._results),
            "source_count":  n,
        }

        logger.info(
            "Fuse | %d kaynak | category=%s brand=%s volume=%s is_empty=%s conf=%d",
            n,
            fused["category"], fused["brand"], fused["volume"],
            fused["is_empty"], fused["confidence"],
        )
        return fused


# ─────────────────────────────────────────────────────────────
# BÖLÜM 5 — AI Konsensüs
# ─────────────────────────────────────────────────────────────

def resolve_ai_consensus(result_a: dict, result_b: dict) -> dict:
    cat_a = (result_a.get("category") or "").strip().lower()
    cat_b = (result_b.get("category") or "").strip().lower()

    if cat_a == cat_b:
        winner = (
            result_a
            if result_a.get("confidence", 0) >= result_b.get("confidence", 0)
            else result_b
        )
        winner = dict(winner)
        winner["consensus"] = "agreed"
        logger.info("Konsensüs: anlaşma → category=%s", cat_a)
        return winner

    logger.warning(
        "Konsensüs: ANLAŞMAZLIK | A=%s B=%s → review kuyruğu",
        cat_a, cat_b
    )
    return {
        "consensus":    "disputed",
        "needs_review": True,
        "result_a":     result_a,
        "result_b":     result_b,
        "category":     None,
    }
