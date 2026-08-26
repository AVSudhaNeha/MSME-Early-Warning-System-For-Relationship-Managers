"""
Judge provider abstraction — Azure OpenAI (default) or Anthropic.

Azure reuses the already-configured variables from app.config.
Anthropic uses ANTHROPIC_API_KEY from .env.
"""

import os
from dotenv import load_dotenv

from .config import JUDGE_PROVIDER, ANTHROPIC_MODEL

# Load variables from project-root .env
load_dotenv()

def get_judge():
    """
    Returns:
        (call_fn, model_name)

    call_fn(prompt: str) -> str
        Sends the prompt to the selected judge provider and returns
        the raw text response.

    Supported providers:
        - azure
        - anthropic
    """

    # ============================================================
    # AZURE OPENAI
    # ============================================================
    if JUDGE_PROVIDER == "azure":

        from openai import AzureOpenAI
        from app import config as app_config

        # Reuse the existing Azure configuration
        if not (
            app_config.AZURE_ENDPOINT
            and app_config.AZURE_API_KEY
            and app_config.AZURE_API_VERSION
            and app_config.AZURE_CHAT_DEPLOYMENT
        ):
            raise RuntimeError(
                "Azure OpenAI credentials/configuration are missing "
                "from .env. Required variables are:\n"
                "AZURE_OPENAI_ENDPOINT\n"
                "AZURE_OPENAI_API_KEY\n"
                "AZURE_OPENAI_API_VERSION\n"
                "AZURE_CHAT_DEPLOYMENT"
            )

        client = AzureOpenAI(
            azure_endpoint=app_config.AZURE_ENDPOINT,
            api_key=app_config.AZURE_API_KEY,
            api_version=app_config.AZURE_API_VERSION,
        )

        def call_fn(prompt: str) -> str:
            response = client.chat.completions.create(
                model=app_config.AZURE_CHAT_DEPLOYMENT,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
                temperature=0,
                max_tokens=700,
            )

            return response.choices[0].message.content

        return call_fn, app_config.AZURE_CHAT_DEPLOYMENT

    # ============================================================
    # ANTHROPIC
    # ============================================================
    if JUDGE_PROVIDER == "anthropic":

        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")

        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is missing from .env."
            )

        if not ANTHROPIC_MODEL:
            raise RuntimeError(
                "ANTHROPIC_MODEL is missing from app/evaluation/config.py."
            )

        client = anthropic.Anthropic(
            api_key=api_key
        )

        def call_fn(prompt: str) -> str:
            response = client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=700,
                temperature=0,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            return response.content[0].text

        return call_fn, ANTHROPIC_MODEL

    # ============================================================
    # INVALID PROVIDER
    # ============================================================
    raise ValueError(
        f"Unknown JUDGE_PROVIDER '{JUDGE_PROVIDER}'. "
        "Use 'azure' or 'anthropic'."
    )