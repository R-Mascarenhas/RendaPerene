import re

B3_TICKER_PATTERN = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{4}\d{1,2}[A-Z]?$")


def normalize_b3_ticker(value: object) -> str:
    """Normalize a B3 ticker or reject values that cannot identify a listed asset."""
    ticker = str(value).strip().upper()
    if not B3_TICKER_PATTERN.fullmatch(ticker):
        raise ValueError("Informe um ticker válido da B3, como PETR4, BOVA11, NUBR33 ou PETR4F.")
    return ticker
