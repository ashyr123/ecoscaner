# config/bonus_brands.py
# Bonus puan veren markalar — AI'dan gelen brand değeriyle eşleştirilir.
# Buraya istediğin markayı ekleyebilirsin.
# multiplier: 1.0 = normal puan, 1.5 = %50 bonus, 2.0 = 2x puan

BONUS_BRANDS: dict[str, float] = {
    # Cola grubu
    "pepsi":        1.5,
    "coca-cola":    1.5,
    "coca cola":    1.5,
    "cocacola":     1.5,
    "fanta":        1.5,
    "sprite":       1.5,

    # Energy içecekleri
    "gorilla":      1.5,
    "gorilla energy": 1.5,
    "red bull":     1.5,
    "redbull":      1.5,
    "monster":      1.5,
    "burn":         1.5,

    # Belarus yerel markaları
    "хомская":      2.0,   # Belarus yereli → 2x bonus
    "минская":      2.0,
    "дарида":       2.0,
    "фруктовый":    1.5,
    "добрый":       1.5,
    "сочный":       1.5,
}


def get_bonus_multiplier(brand: str) -> tuple[float, bool]:
    """
    Verilen marka için bonus çarpanı döner.
    Returns: (multiplier, is_bonus)
      - multiplier: float (1.0 = bonus yok)
      - is_bonus: True ise kullanıcıya bonus mesajı göster
    """
    if not brand or brand.strip().upper() == "UNKNOWN":
        return 1.0, False

    key = brand.strip().lower()

    # Tam eşleşme
    if key in BONUS_BRANDS:
        return BONUS_BRANDS[key], True

    # Kısmi eşleşme — "Gorilla Energy Drink 0.5L" gibi uzun brand'ler için
    for b, mult in BONUS_BRANDS.items():
        if b in key or key in b:
            return mult, True

    return 1.0, False