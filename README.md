# Botmother Flow Agent

LangGraph-based conversational agent that generates valid flow JSON for the Botmother engine.

## Setup

```bash
pip install -r requirements.txt
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=sk-...
```

## Usage

```bash
python -m botmother_agent.cli
```

Or after installing:
```bash
botmother-agent
```

The agent will start a conversation. Tell it what kind of Telegram bot you want, and it will:
1. Ask clarifying questions about your requirements
2. Generate a valid flow JSON
3. Save it to the `flows/` directory

## Example

```
You: Men pizza buyurtma berish botini yaratmoqchiman
Agent: Ajoyib! Pizza buyurtma bot uchun bir nechta savol:
1. Qanday kategoriyalar bo'ladi? (masalan: pizza, ichimliklar, desertlar)
2. To'lov qanday bo'ladi? (click, payme, naqd)
...
```
