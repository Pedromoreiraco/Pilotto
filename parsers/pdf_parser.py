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


SKIP_DESCRIPTION_KEYWORDS = [
    "total", "saldo", "subtotal", "saldo anterior", "saldo atual",
    "saldo disponível", "saldo final", "saldo inicial", "limite",
    "total de débitos", "total de créditos", "total geral",
]

INCOME_KEYWORDS = [
    "salário", "salario", "pagamento recebido", "transferência recebida",
    "transferencia recebida", "pix recebido", "ted recebida", "doc recebido",
    "depósito", "deposito", "crédito em conta", "credito em conta",
    "rendimento", "dividendo", "reembolso", "estorno", "devolução", "devolucao",
]


def _parse_value(raw: str) -> tuple[float, str | None]:
    raw = raw.strip().replace("R$", "").replace("\xa0", "").replace(" ", "")
    credit_flag = None
    if raw.upper().endswith("C"):
        credit_flag = "credit"
        raw = raw[:-1]
    elif raw.upper().endswith("D"):
        credit_flag = "debit"
        raw = raw[:-1]
    negative = raw.endswith("-") or raw.startswith("-")
    raw = raw.strip("+-")
    raw = raw.replace(".", "").replace(",", ".")
    value = float(raw)
    if credit_flag == "credit":
        return abs(value), "credit"
    if credit_flag == "debit":
        return -abs(value), "debit"
    return -abs(value) if negative else value, None


def _should_skip(description: str) -> bool:
    desc_lower = description.lower().strip()
    return any(kw in desc_lower for kw in SKIP_DESCRIPTION_KEYWORDS)


def _infer_type_from_description(description: str) -> str | None:
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in INCOME_KEYWORDS):
        return "credit"
    return None


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
        r"(R?\$?\s*-?\s*\d{1,3}(?:\.\d{3})*,\d{2}\s*[-+CD]?)"
        r"(?:\s|$)",
        re.MULTILINE,
    )

    for match in pattern.finditer(text):
        date_str, description, value_str = match.groups()
        date = _parse_date(date_str, year_hint)
        if not date:
            continue
        try:
            value, type_hint = _parse_value(value_str)
        except (ValueError, AttributeError):
            continue

        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 3 or _should_skip(description):
            continue

        tx_type = type_hint or _infer_type_from_description(description) or ("credit" if value >= 0 else "debit")
        if tx_type == "credit":
            value = abs(value)

        transactions.append({"date": date, "description": description, "value": value, "type": tx_type})

    return transactions


def _parse_itau_format(text: str, year_hint: Optional[int]) -> list[dict]:
    transactions = []
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        m = re.match(
            r"(\d{2}/\d{2})\s+(.+?)\s+([\d\.]+,\d{2})([-+CD]?)\s*$", line, re.IGNORECASE
        )
        if not m:
            continue
        date_str, description, value_str, sign = m.groups()
        date = _parse_date(date_str, year_hint)
        if not date:
            continue
        try:
            value, type_hint = _parse_value(value_str + sign)
        except ValueError:
            continue

        description = re.sub(r"\s+", " ", description).strip()
        if _should_skip(description):
            continue

        tx_type = type_hint or _infer_type_from_description(description) or ("credit" if value >= 0 else "debit")
        if tx_type == "credit":
            value = abs(value)

        transactions.append({"date": date, "description": description, "value": value, "type": tx_type})

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
            value, _ = _parse_value(value_str)
        except ValueError:
            continue

        description = re.sub(r"\s+", " ", description).strip()
        if len(description) < 3 or _should_skip(description):
            continue

        tx_type = _infer_type_from_description(description) or "debit"
        value = abs(value) if tx_type == "credit" else -abs(value)

        transactions.append({"date": date, "description": description, "value": value, "type": tx_type})

    return transactions


def _is_credit_card_statement(text: str) -> bool:
    indicators = [
        "fatura", "cartão de crédito", "credito", "limite", "vencimento",
        "pagamento mínimo", "pagamento minimo", "total da fatura",
    ]
    text_lower = text.lower()
    return sum(1 for ind in indicators if ind in text_lower) >= 2


def _normalize_header(h: str) -> str:
    import unicodedata
    h = unicodedata.normalize("NFD", str(h or ""))
    h = "".join(c for c in h if unicodedata.category(c) != "Mn")
    return h.lower().strip()


def _parse_table(file_path: str, year_hint: Optional[int]) -> list[dict]:
    transactions = []
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    if not table or len(table) < 2:
                        continue
                    header_idx = None
                    header = None
                    for i, row in enumerate(table):
                        norm = [_normalize_header(c) for c in (row or [])]
                        if any("historico" in c or "descri" in c or "lancamento" in c for c in norm):
                            if any("data" in c for c in norm):
                                header_idx = i
                                header = norm
                                break
                    if header is None:
                        continue

                    def col(keywords):
                        for kw in keywords:
                            for i, h in enumerate(header):
                                if kw in h:
                                    return i
                        return None

                    i_date = col(["data"])
                    i_desc = col(["historico", "descricao", "descri", "lancamento"])
                    i_cred = col(["credito", "credit", "entrada"])
                    i_deb  = col(["debito", "debit", "saida"])
                    i_val  = col(["valor"]) if (i_cred is None and i_deb is None) else None

                    if i_date is None or i_desc is None:
                        continue

                    for row in table[header_idx + 1:]:
                        if not row:
                            continue
                        def cell(i):
                            if i is None or i >= len(row):
                                return ""
                            return str(row[i] or "").strip()

                        date = _parse_date(cell(i_date), year_hint)
                        if not date:
                            continue
                        description = re.sub(r"\s+", " ", cell(i_desc)).strip()
                        if not description or len(description) < 2 or _should_skip(description):
                            continue

                        value = None
                        if i_cred is not None and i_deb is not None:
                            cred_raw = cell(i_cred)
                            deb_raw  = cell(i_deb)
                            if cred_raw and re.search(r"\d", cred_raw):
                                try:
                                    v, _ = _parse_value(cred_raw)
                                    value = abs(v)
                                except ValueError:
                                    pass
                            elif deb_raw and re.search(r"\d", deb_raw):
                                try:
                                    v, _ = _parse_value(deb_raw)
                                    value = -abs(v)
                                except ValueError:
                                    pass
                        elif i_val is not None:
                            raw = cell(i_val)
                            if raw and re.search(r"\d", raw):
                                try:
                                    v, type_hint = _parse_value(raw)
                                    inferred = type_hint or _infer_type_from_description(description)
                                    value = abs(v) if inferred == "credit" else -abs(v)
                                except ValueError:
                                    pass

                        if value is None or value == 0:
                            continue
                        tx_type = "credit" if value > 0 else "debit"
                        transactions.append({"date": date, "description": description, "value": value, "type": tx_type})
    except Exception:
        pass
    return transactions


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

    table_transactions = _parse_table(file_path, year_hint)
    if table_transactions:
        return table_transactions

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
