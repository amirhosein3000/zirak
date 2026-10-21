from datetime import UTC, datetime

from zirak.i18n import en_digits, fa_num, fa_pct, gregorian_to_jalali, tehran_time


def test_jalali_known_dates() -> None:
    assert gregorian_to_jalali(2026, 3, 21) == (1405, 1, 1)  # Nowruz 1405
    assert gregorian_to_jalali(2025, 3, 20) == (1403, 12, 30)  # leap Esfand
    assert gregorian_to_jalali(2026, 10, 11) == (1405, 7, 19)


def test_tehran_time_is_utc_plus_330() -> None:
    assert tehran_time(datetime(2026, 10, 11, 15, 0, tzinfo=UTC)) == "۱۹ مهر ۱۴۰۵، ۱۸:۳۰"


def test_number_formatting() -> None:
    assert fa_num(1234567.891, 2) == "۱٬۲۳۴٬۵۶۷٫۸۹"
    assert fa_num(5, 0) == "۵"
    assert fa_pct(3.0) == "۳٪"
    assert en_digits("۵٪ و ۱۰٫۵") == "5٪ و 10.5"
