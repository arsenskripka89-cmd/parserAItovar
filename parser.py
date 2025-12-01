"""Demonstration script for making an OpenAI Chat Completions request."""
from __future__ import annotations

from openai import AuthenticationError, OpenAIError

from config import get_openai_client


PROMPT = "Скажи короткий привітальний текст"  # Впишіть свій ключ у config.json або через OPENAI_API_KEY


def main() -> None:
    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": PROMPT}],
            max_tokens=50,
        )
        message_content = response.choices[0].message.content
        print(f"Відповідь від моделі: {message_content}")
    except RuntimeError as error:
        print(error)
    except AuthenticationError:
        print(
            "Помилка автентифікації OpenAI. Перевір правильність ключа в config.json або змінній OPENAI_API_KEY."
        )
    except OpenAIError as error:
        print(f"Сталася помилка OpenAI API: {error}")
    except Exception as error:  # Fallback to avoid raw traceback in console
        print(f"Неочікувана помилка: {error}")


if __name__ == "__main__":
    main()
