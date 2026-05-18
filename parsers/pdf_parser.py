import re
import pdfplumber
from datetime import datetime
from typing import Optional


DATE_PATTERNS = [
    r"\b(\d{2}/\d{2}/\d{4})\b",
    r"\b(\d{2}/\d{2}/\d{2})\b",
    r"\b(\d{2}-\d{2}-\d{4})\b",
]

VALUE_PATTERN = r"R?\$?\s*-?\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2}))"

BANK_PATTERNS = {
    "itau": {
        "transaction_line": re.compile(
            r"(\d{2}/\d{2})\s+(.+?)\s+([\d\.]+,\d{2}[-+]?)\s*$", re.MULTILINE
        ),
    },
    "bradesco": {
        "transaction_line": re.compile(
            r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d\.]+,\d{2})\s*$", re.MULTILINE
        ),
    },
    "santander": {
        "transaction_line": re.compile(
            r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d\.]+,\d{2})\s*$", re.MULTILINE
        ),
    },
    "bb": {
        "transaction_line": re.compile(
            r"(\d{2}/\d{2}/\d{4})\s+(.+?)\s+(-?[\d\.]+,\d{2})\s*$", re.MULTILINE
        ),
    },
    "nubank": {
        "transaction_line": re.compile(
            r"(\d{2}\s+\w{3})\s+(.+?)\s+(-?[\d\.]+,\d{2})\s*$", re.MULTILINE
        ),
    },
}

MONTH_MAP = {
    "jan": "01", "fev": "02", "mar": "03", "abr": "04",
    "mai": "05", "jun": "06", "jul": "07", "ago": "08",
    "set": "09", "out": "10", "nov": "11", "dez": "12",
}


def _parse_value(raw: str) -> float:
    raw = raw.strip().replace("R$", "").replace(" ", "")
    negative = raw.endswith("-") or raw.startswith("-")
    raw = raw.strip("+-")
    raw = raw.replace(".", "").replace(",", ".")
    value = float(raw)
    return -abs(value) if negative else value


def _parse_date(raw: str, year_hint: Optional[int] = None) -> Optional[datetime]:
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    m = re.match(r"(\d{2})/(\d{2})$", raw)
    if m:
        day, month = m.groups()
        year = year_hint or datetime.today().year
        try:
            return datetime(year, int(month), int(day))
        except ValueError:
            pass

    m = re.match(r"(\d{2})\s+(\w{3})$", raw, re.IGNORECASE)
    if m:
        day, mon_str = m.groups()
        month = MONTH_MAP.get(mon_str.lower())
        if month:
            year = year_hint or datetime.today().year
            try:
                return datetime(year, int(month), int(day))
            except ValueError:
                pass

    return None


def _detect_bank(text: str) -> str:
    text_lower = text.lower()
    if "itaú" in text_lower or "itau" in text_lower:
        return "itau"
    if "bradesco" in text_lower:
        return "bradesco"
    if "santander" in text_lower:
        return "santander"
    if "banco do brasil" in text_lower or "bb.com" in text_lower:
        return "bb"
    if "nubank" in text_lower or "nu pagamentos" in text_lower:
        return "nubank"
    return "generic"


def _extract_year_from_text(text: str) -> Optional[int]:
    matches = re.findall(r"\b(20\d{2})\b", text)
    if matches:
        from collections import Counter
        return int(Counter(matches).most_common(1)[0][0])
    return None


def _parse_generic(text: str, year_hint: Optional[int]) -> list[dict]:
    transactions = []

    pattern = re.compile(
        r"(\d{2}/\d{2}/\d{4}|\d{2}/\d{2}/\d{2}|\d{2}/\d{2})"
        r"\s+"
        r"(.{5,60}?)"
        r"\s+"
        r"(R?\$?\s*-?\s*\d{1,3}(?:\.\d{3})*,\d{2}\s*[-+]?)"
        r"(?:\s|$)",
        re.MULTILINE,
    )

    for match in pattern.finditer(text):
        date_str, description, value_str = match.groups()
        date = _parse_date(date_str, year_hint)
        if not date:
            continue
        try:
            value = _parse_value(value_str)
        except (ValueError, AttributeError):
            continue

        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 3:
            continue

        transactions.append({
            "date": date,
            "description": description,
            "value": value,
            "type": "credit" if value >= 0 else "debit",
        })

    return transactions


def _parse_itau_format(text: str, year_hint: Optional[int]) -> list[dict]:
    transactions = []
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        m = re.match(
            r"(\d{2}/\d{2})\s+(.+?)\s+([\d\.]+,\d{2})([-+]?)\s*$", line
        )
        if not m:
            continue
        date_str, description, value_str, sign = m.groups()
        date = _parse_date(date_str, year_hint)
        if not date:
            continue
        try:
            value = _parse_value(value_str + sign)
        except ValueError:
            continue

        description = re.sub(r"\s+", " ", description).strip()
        transactions.append({
            "date": date,
            "description": description,
            "value": value,
            "type": "credit" if value >= 0 else "debit",
        })

    return transactions


def _parse_credit_card(text: str, year_hint: Optional[int]) -> list[dict]:
    transactions = []

    pattern = re.compile(
        r"(\d{2}/\d{2}(?:/\d{2,4})?)"
        r"\s+"
        r"(.{4,60}?)"
        r"\s+"
        r"(R?\$?\s*-?\s*\d{1,3}(?:\.\d{3})*,\d{2})"
        r"(?:\s|$)",
        re.MULTILINE,
    )

    for match in pattern.finditer(text):
        date_str, description, value_str = match.groups()
        date = _parse_date(date_str, year_hint)
        if not date:
            continue
        try:
            value = _parse_value(value_str)
        except ValueError:
            continue

        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 3:
            continue

        if value > 0:
            value = -value

        transactions.append({
            "date": date,
            "description": description,
            "value": value,
            "type": "debit",
        })

    return transactions


def _is_credit_card_statement(text: str) -> bool:
    indicators = [
        "fatura", "cartão de crédito", "credito", "limite", "vencimento",
        "pagamento mínimo", "pagamento minimo", "total da fatura",
    ]
    text_lower = text.lower()
    return sum(1 for ind in indicators if ind in text_lower) >= 2


def parse_pdf(file_path: str) -> list[dict]:
    try:
        full_text = ""
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
    except Exception as e:
        raise ValueError(f"Não foi possível ler o PDF: {e}")

    if not full_text.strip():
        raise ValueError("O PDF não contém texto extraível. Pode ser um PDF escaneado.")

    year_hint = _extract_year_from_text(full_text)
    bank = _detect_bank(full_text)
    is_cc = _is_credit_card_statement(full_text)

    if is_cc:
        transactions = _parse_credit_card(full_text, year_hint)
        if transactions:
            return transactions

    if bank == "itau":
        transactions = _parse_itau_format(full_text, year_hint)
        if transactions:
            return transactions

    transactions = _parse_generic(full_text, year_hint)

    if not transactions:
        raise ValueError(
            "Nenhuma transação encontrada no PDF. "
            "Verifique se o arquivo é um extrato bancário válido."
        )

    return transactions
