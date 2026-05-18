import pandas as pd
import re
from datetime import datetime
from typing import Optional


DATE_COLUMN_NAMES = [
    "data", "date", "dt", "data lançamento", "data lancamento",
    "data transação", "data transacao", "dt transação", "dt transacao",
    "data mov", "data movimento", "competência", "competencia",
]

DESCRIPTION_COLUMN_NAMES = [
    "descrição", "descricao", "description", "histórico", "historico",
    "lançamento", "lancamento", "memo", "observação", "observacao",
    "complemento", "detalhe", "detalhes", "estabelecimento", "local",
    "favorecido", "nome",
]

VALUE_COLUMN_NAMES = [
    "valor", "value", "amount", "quantia", "montante",
    "débito", "debito", "crédito", "credito",
]

DEBIT_COLUMN_NAMES = ["débito", "debito", "saída", "saida", "debit"]
CREDIT_COLUMN_NAMES = ["crédito", "credito", "entrada", "entrada", "credit"]


def _normalize_col(name: str) -> str:
    return (
        str(name)
        .lower()
        .strip()
        .replace("é", "e")
        .replace("ê", "e")
        .replace("ã", "a")
        .replace("â", "a")
        .replace("ç", "c")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ô", "o")
        .replace("ú", "u")
        .replace("á", "a")
    )


def _find_column(df: pd.DataFrame, candidates: list[str]) -> Optional[str]:
    normalized_cols = {_normalize_col(c): c for c in df.columns}
    for candidate in candidates:
        norm_candidate = _normalize_col(candidate)
        if norm_candidate in normalized_cols:
            return normalized_cols[norm_candidate]
    for candidate in candidates:
        norm_candidate = _normalize_col(candidate)
        for norm_col, orig_col in normalized_cols.items():
            if norm_candidate in norm_col:
                return orig_col
    return None


def _parse_value(raw) -> Optional[float]:
    if pd.isna(raw):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip()
    s = s.replace("R$", "").replace(" ", "")
    negative = s.startswith("-") or s.endswith("-")
    s = s.strip("+-")
    s = re.sub(r"[^\d,\.]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        value = float(s)
        return -abs(value) if negative else value
    except ValueError:
        return None


def _parse_date(raw) -> Optional[datetime]:
    if pd.isna(raw):
        return None
    if isinstance(raw, datetime):
        return raw
    if hasattr(raw, "to_pydatetime"):
        return raw.to_pydatetime()
    s = str(raw).strip()
    formats = [
        "%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y",
        "%d.%m.%Y", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _find_header_row(df_raw: pd.DataFrame) -> int:
    for i, row in df_raw.iterrows():
        row_str = " ".join(str(v).lower() for v in row.values if pd.notna(v))
        if any(
            kw in row_str
            for kw in ["data", "descri", "valor", "hist", "lancamento", "lançamento"]
        ):
            return i
    return 0


def _load_file(file_path: str) -> pd.DataFrame:
    if file_path.endswith(".csv"):
        for sep in [";", ",", "\t"]:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding="utf-8", header=None)
                if df.shape[1] >= 2:
                    break
            except Exception:
                continue
        else:
            df = pd.read_csv(file_path, encoding="latin-1", header=None)
    else:
        df = pd.read_excel(file_path, header=None, engine="openpyxl")
    return df


def parse_excel(file_path: str) -> list[dict]:
    try:
        df_raw = _load_file(file_path)
    except Exception as e:
        raise ValueError(f"Não foi possível ler o arquivo: {e}")

    header_row = _find_header_row(df_raw)
    df_raw.columns = df_raw.iloc[header_row]
    df = df_raw.iloc[header_row + 1 :].reset_index(drop=True)
    df = df.dropna(how="all")

    date_col = _find_column(df, DATE_COLUMN_NAMES)
    desc_col = _find_column(df, DESCRIPTION_COLUMN_NAMES)
    value_col = _find_column(df, VALUE_COLUMN_NAMES)
    debit_col = _find_column(df, DEBIT_COLUMN_NAMES)
    credit_col = _find_column(df, CREDIT_COLUMN_NAMES)

    if not date_col:
        for col in df.columns:
            sample = df[col].dropna().head(5)
            for val in sample:
                if _parse_date(val):
                    date_col = col
                    break
            if date_col:
                break

    if not desc_col:
        best_col = None
        best_score = -1
        for col in df.columns:
            if col == date_col:
                continue
            sample = df[col].dropna().head(10)
            text_vals = [str(v) for v in sample if not str(v).replace(" ", "").isdigit()]
            score = sum(len(v) for v in text_vals)
            if score > best_score and len(text_vals) >= 2:
                best_score = score
                best_col = col
        desc_col = best_col

    if not value_col and not (debit_col and credit_col):
        for col in df.columns:
            if col in (date_col, desc_col):
                continue
            sample = df[col].dropna().head(10)
            parsed = [_parse_value(v) for v in sample if _parse_value(v) is not None]
            if len(parsed) >= 3:
                value_col = col
                break

    if not date_col or not desc_col:
        raise ValueError(
            "Não foi possível identificar as colunas de data e descrição. "
            "Verifique se o arquivo está no formato correto."
        )

    transactions = []
    for _, row in df.iterrows():
        date = _parse_date(row.get(date_col))
        if not date:
            continue

        description = str(row.get(desc_col, "")).strip()
        if not description or description.lower() in ("nan", "none", ""):
            continue

        value = None
        if debit_col and credit_col:
            debit = _parse_value(row.get(debit_col))
            credit = _parse_value(row.get(credit_col))
            if debit and not pd.isna(debit):
                value = -abs(debit)
            elif credit and not pd.isna(credit):
                value = abs(credit)
        elif value_col:
            value = _parse_value(row.get(value_col))

        if value is None or value == 0:
            continue

        description = re.sub(r"\s+", " ", description).strip()

        skip_keywords = [
            "total", "saldo", "subtotal", "saldo anterior", "saldo atual",
            "saldo final", "saldo inicial", "limite", "total de débitos",
            "total de créditos", "total geral",
        ]
        if any(kw in description.lower() for kw in skip_keywords):
            continue

        transactions.append({
            "date": date,
            "description": description,
            "value": value,
            "type": "credit" if value >= 0 else "debit",
        })

    if not transactions:
        raise ValueError(
            "Nenhuma transação encontrada no arquivo. "
            "Verifique se o arquivo contém dados válidos."
        )

    return transactions
