import anthropic
from typing import Optional


SYSTEM_PROMPT = """Você é um assistente especializado em categorizar transações financeiras brasileiras.

Sua tarefa é categorizar cada transação em uma das categorias fornecidas.

Regras importantes:
- Responda SOMENTE com a lista de categorias, uma por linha, na mesma ordem das transações
- Use exatamente o nome da categoria como fornecido
- Se não tiver certeza, use "Outros"
- Transações com valores positivos (receitas) geralmente são "Receita"
- Não adicione explicações, numeração ou qualquer outro texto"""


def categorize_batch(
    transactions: list[dict],
    categories: list[str],
    api_key: Optional[str] = None,
    batch_size: int = 50,
) -> list[str]:
    if not transactions:
        return []

    try:
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    except Exception:
        return ["Outros"] * len(transactions)

    results = []
    categories_str = "\n".join(f"- {c}" for c in categories)

    for i in range(0, len(transactions), batch_size):
        batch = transactions[i : i + batch_size]
        batch_results = _categorize_single_batch(client, batch, categories, categories_str)
        results.extend(batch_results)

    return results


def _categorize_single_batch(
    client: anthropic.Anthropic,
    transactions: list[dict],
    categories: list[str],
    categories_str: str,
) -> list[str]:
    lines = []
    for t in transactions:
        value_str = f"R$ {abs(t['value']):.2f}".replace(".", ",")
        direction = "entrada" if t["value"] >= 0 else "saída"
        lines.append(f"{t['description']} ({direction} {value_str})")

    transactions_text = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))

    user_message = f"""Categorias disponíveis:
{categories_str}

Transações para categorizar:
{transactions_text}

Responda com uma categoria por linha, na mesma ordem das transações acima."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )

        response_text = response.content[0].text.strip()
        response_lines = [line.strip() for line in response_text.split("\n") if line.strip()]

        result = []
        for line in response_lines:
            line = line.lstrip("0123456789.-) ").strip()
            if line in categories:
                result.append(line)
            else:
                matched = next(
                    (c for c in categories if c.lower() == line.lower()), "Outros"
                )
                result.append(matched)

        while len(result) < len(transactions):
            result.append("Outros")

        return result[: len(transactions)]

    except anthropic.AuthenticationError:
        return ["Outros"] * len(transactions)
    except anthropic.RateLimitError:
        return ["Outros"] * len(transactions)
    except Exception:
        return ["Outros"] * len(transactions)
