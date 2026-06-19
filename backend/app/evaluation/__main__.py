"""Lance l'évaluation LLM vs baseline contre le générateur réel (Ollama/HF).

Usage : `make eval` (ou `PYTHONPATH=backend uv run python -m app.evaluation`).
"""

import asyncio

from app.adapters.llm_openai import OpenAICompatibleStrategyGenerator
from app.evaluation.runner import format_report, run_evaluation


async def _main() -> None:
    rows = await run_evaluation(OpenAICompatibleStrategyGenerator())
    print(format_report(rows))


if __name__ == "__main__":
    asyncio.run(_main())
