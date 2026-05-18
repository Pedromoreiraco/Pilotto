import re
import unicodedata
import pandas as pd
from typing import Union


def _clean_description(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    text = re.sub(r"[^\w\s\-\./,áàãâéêíóôõúüçñÁÀÃÂÉÊÍÓÔÕÚÜÇÑ]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_transactions(
    transactions: list[dict], source_name: str = ""
) -> pd.DataFrame:
    if not transactions:
        return pd.DataFrame(
            columns=["date", "description", "value", "type", "source"]
        )

    rows = []
    for t in transactions:
        date = pd.to_datetime(t.get("date"), errors="coerce")
        if pd.isna(date):
            continue

        description = _clean_description(str(t.get("description", "")))
        if not description:
            continue

        raw_value = t.get("value", 0)
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue

        tx_type = t.get("type", "debit" if value < 0 else "credit")

        rows.append({
            "date": date,
            "description": description,
            "value": value,
            "type": tx_type,
            "source": source_name,
        })

    if not rows:
        return pd.DataFrame(
            columns=["date", "description", "value", "type", "source"]
        )

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df
