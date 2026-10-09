import json
import os
from dataclasses import dataclass, field
from datetime import date

from startright.tools import TOOLS, run_tool

SYSTEM_PROMPT = (
    "You are StartRight, an assistant that helps people in Zimbabwe understand "
    "business registration, tax and compliance. Today's date is {today}.\n"
    "Rules:\n"
    "1. For any question about what the law or an official notice requires, call "
    "search_regulations first. Never state rules, fees, rates, form numbers, section "
    "numbers or due dates from memory.\n"
    "2. Use calculate_fees for any total and check_deadline for any date arithmetic. "
    "Never do these sums yourself. Call check_deadline only AFTER search_regulations "
    "has returned the rule that gives the day of the month.\n"
    "3. Answer ONLY from tool results. Cite search results like [1] with the title, "
    "and only cite a number that search_regulations actually returned in this "
    "conversation. If the results do not contain the answer, say so and recommend "
    "confirming with the relevant official office.\n"
    "4. Do not treat different legal entity types as the same thing.\n"
    "5. If the question is not about business registration, tax or compliance in "
    "Zimbabwe, politely decline without calling any tool.\n"
    "6. This is general information, not legal advice."
)


@dataclass
class Step:
    tool: str
    arguments: dict
    result: dict


@dataclass
class AgentResult:
    answer: str
    steps: list[Step] = field(default_factory=list)
    tokens: int = 0


def _has_searched(steps: list[Step]) -> bool:
    """True once search_regulations has returned at least one source."""
    return any(
        step.tool == "search_regulations" and step.result.get("results")
        for step in steps
    )


def run_agent(
    question: str,
    client=None,
    model: str | None = None,
    max_steps: int = 5,
    today: date | None = None,
) -> AgentResult:
    """Let the model choose tools until it can answer, up to max_steps rounds."""
    if client is None:
        from groq import Groq

        client = Groq()  # reads GROQ_API_KEY from the environment
    model = model or os.environ["GROQ_MODEL"]
    today = today or date.today()
    # gpt-oss models think before answering; keep that effort low to save tokens.
    extra = {"reasoning_effort": "low"} if "gpt-oss" in model else {}

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(today=today.isoformat())},
        {"role": "user", "content": question},
    ]
    steps: list[Step] = []
    tokens = 0

    for _ in range(max_steps):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_completion_tokens=1000,
            **extra,
        )
        if response.usage:
            tokens += response.usage.total_tokens
        message = response.choices[0].message
        calls = message.tool_calls or []

        if not calls:
            text = message.content or "The model returned an empty answer."
            return AgentResult(answer=text, steps=steps, tokens=tokens)

        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments or "{}",
                        },
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                if not isinstance(args, dict):
                    raise ValueError("arguments must be a JSON object")
            except ValueError:
                args, result = {}, {"error": "Arguments were not valid JSON"}
            else:
                if name == "check_deadline" and not _has_searched(steps):
                    # Guardrail in code, not just in the prompt: a deadline day
                    # must come from a source, never from the model's memory.
                    result = {
                        "error": "Call search_regulations first to find which day "
                        "of the month the deadline falls on, then call "
                        "check_deadline."
                    }
                else:
                    result = run_tool(name, args, today)
            steps.append(Step(name, args, result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )

    return AgentResult(
        answer=(
            "I could not finish within the step limit. Please try a more specific "
            "question, or confirm with the relevant official office."
        ),
        steps=steps,
        tokens=tokens,
    )
