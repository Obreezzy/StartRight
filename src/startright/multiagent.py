"""A small team of agents wired together with LangGraph.

    coordinate -> specialists -> verify -> (revise once) -> compose

Shared state (a dict that every node reads and updates) carries the plan, each
specialist's findings, the next free citation number, any problems the verifier
found, and a running token count.
"""
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

from startright.agent import SYSTEM_PROMPT, AgentResult, Step, run_agent
from startright.tools import TOOLS

MAX_REVISIONS = 1
MAX_SUBTASKS = 3

DECLINE_MESSAGE = (
    "I can only help with questions about business registration, tax and "
    "compliance in Zimbabwe."
)
FOOTER = (
    "This is general information, not legal advice. Please confirm with the "
    "relevant official office."
)


@dataclass(frozen=True)
class Specialist:
    title: str
    description: str
    scope: tuple[str, ...]  # SQL LIKE patterns for the documents it may search
    tools: tuple[str, ...]


SPECIALISTS: dict[str, Specialist] = {
    "registration": Specialist(
        title="Registration and licensing",
        description=(
            "the Companies and Other Business Entities Act 2019 and the Harare "
            "business licence application form"
        ),
        scope=("cobe_act_2019.pdf", "harare_shop_licence_form.pdf"),
        tools=("search_regulations", "calculate_fees"),
    ),
    "tax": Specialist(
        title="Tax",
        description=(
            "the Value Added Tax Act, the Finance Act 2024 and ZIMRA public notices"
        ),
        scope=("vat_act.pdf", "finance_act_2024.pdf", "zimra_pn_%"),
        tools=("search_regulations", "check_deadline", "calculate_fees"),
    ),
    "employment": Specialist(
        title="Employment and social security",
        description=(
            "the Labour Act, the Labour Amendment Act 2023 and the National Social "
            "Security Authority Act"
        ),
        scope=("labour_act.pdf", "labour_amendment_2023.pdf", "nssa_act.pdf"),
        tools=("search_regulations", "calculate_fees"),
    ),
}

COORDINATOR_PROMPT = (
    "You are the coordinator of a team that answers questions about business "
    "registration, tax and compliance in Zimbabwe. Specialists:\n"
    "- registration: registering companies and other business entities, and "
    "business or shop licences\n"
    "- tax: VAT, income tax, ZIMRA notices, tax returns and due dates\n"
    "- employment: labour law, leave, employees and the National Social Security "
    "Authority\n"
    "Decide which specialists are needed (usually one, at most three) and write a "
    "self-contained task for each. Use full names instead of acronyms. A task must "
    "only restate what to find out. Do NOT answer the question, do NOT put facts, "
    "figures, dates or deadlines in a task, and do NOT say something cannot be done: "
    "specialists can search the documents and can work out dates, because they know "
    "today's date. If the question is not about business registration, tax or "
    "compliance in Zimbabwe, decline. Reply with JSON only, no other text, in "
    "exactly this shape:\n"
    '{"decline": false, "subtasks": [{"agent": "tax", "task": "..."}]}'
)

KEYWORDS = {
    "registration": ("regist", "company", "business", "licen", "incorporat", "shop",
                     "council", "trading"),
    "tax": ("vat", "tax", "zimra", "return", "paye", "income", "revenue"),
    "employment": ("employ", "labour", "labor", "nssa", "social security", "leave",
                   "worker", "wage", "salary", "dismiss"),
}

CITATION = re.compile(r"[\[【](\d+)[\]】]")


class State(TypedDict, total=False):
    question: str
    subtasks: list[dict]
    declined: bool
    plan_source: str
    findings: list[dict]
    issues: list[dict]
    rerun: list[int]
    feedback: dict
    revisions: int
    tokens: int
    answer: str


@dataclass
class TeamResult:
    answer: str
    subtasks: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)
    revisions: int = 0
    tokens: int = 0
    plan_source: str = "model"


# ---------- pure helpers (no model, easy to test) ----------

def parse_plan(text: str) -> tuple[list[dict], bool] | None:
    """Read the coordinator's JSON reply. Returns (subtasks, declined) or None."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    if data.get("decline") is True:
        return [], True
    subtasks, seen = [], set()
    for item in data.get("subtasks") or []:
        if not isinstance(item, dict):
            continue
        agent, task = item.get("agent"), str(item.get("task") or "").strip()
        if agent in SPECIALISTS and task and agent not in seen:
            seen.add(agent)
            subtasks.append({"agent": agent, "task": task})
    if not subtasks:
        return None
    return subtasks[:MAX_SUBTASKS], False


def keyword_route(question: str) -> tuple[list[dict], bool]:
    """Fallback when the coordinator's reply cannot be read."""
    lowered = question.lower()
    subtasks = [
        {"agent": agent, "task": question}
        for agent, words in KEYWORDS.items()
        if any(word in lowered for word in words)
    ]
    return (subtasks[:MAX_SUBTASKS], False) if subtasks else ([], True)


ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()

RANGE = r"\d+(?:\.\d+)?(?:\s?[–-]\s?\d+(?:\.\d+)?)?"
CLAIMS = [
    ("percent", re.compile(rf"(?P<nums>{RANGE})\s?(?:%|per\s?cent)", re.I)),
    ("period", re.compile(
        rf"(?P<nums>{RANGE})\s+(?:business\s+|working\s+|calendar\s+)?days?\b", re.I)),
    ("cents", re.compile(r"(?P<nums>\d+)\s+cents?\b", re.I)),
    ("amount", re.compile(
        r"(?:US\$|USD|ZWL|ZWG|ZiG|\$)\s?(?P<nums>\d[\d,]*(?:\.\d+)?)", re.I)),
    ("amount", re.compile(
        r"\b(?P<nums>\d[\d,]*(?:\.\d+)?)\s?(?:USD|ZWL|ZWG|ZiG)\b", re.I)),
    ("form", re.compile(
        r"\bForm\s+(?P<name>(?=[A-Za-z0-9‑\-]*\d)[A-Za-z0-9‑\-]+|[A-Z]{2,}[A-Za-z0-9‑\-]*)")),
]
UNIT_SUFFIX = {
    "percent": r"\s?(?:%|per\s?cent)",
    "period": r"\s*(?:\(\d+\)\s*)?(?:business\s+|working\s+|calendar\s+)?days?\b",
    "cents": r"\s*cents?\b",
}


def number_words(n: int) -> str:
    """98 -> 'ninety-eight' (Acts often write numbers out in words)."""
    if n < 20:
        return ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return TENS[tens] + (f"-{ONES[ones]}" if ones else "")
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return ONES[hundreds] + " hundred" + (f" and {number_words(rest)}" if rest else "")
    return str(n)


def _normalise(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d)", "", text.lower())
    return text.replace("‑", "-").replace("–", "-").replace("—", "-")


def _number_is_grounded(num: str, kind: str, evidence: str) -> bool:
    if kind == "amount":
        wanted = float(num)
        return any(
            abs(float(found) - wanted) < 1e-9
            for found in re.findall(r"\d+(?:\.\d+)?", evidence)
        )
    suffix = UNIT_SUFFIX[kind]
    if re.search(rf"(?<![\d.]){re.escape(num)}{suffix}", evidence):
        return True
    if "." not in num:
        words = number_words(int(num)).replace("-", r"[\s-]").replace(" ", r"\s+")
        return bool(re.search(rf"\b{words}\b{suffix}", evidence))
    return False


def ungrounded_claims(answer: str, evidence: str, loose_evidence: str = "") -> list[str]:
    """Figures, fees, day counts and form names in the answer that appear in no
    source, tool result or user question. This catches invented specifics, not
    every wrong claim.

    evidence is the text of search results: a figure must appear there next to its
    unit. loose_evidence is the user's question plus calculator and date-tool
    results: any matching number counts, because a tool may return -91 where the
    answer says "91 days ago".
    """
    evidence = _normalise(evidence)
    loose = _normalise(loose_evidence)
    loose_numbers = {abs(float(x)) for x in re.findall(r"\d+(?:\.\d+)?", loose)}
    flagged: list[str] = []
    for kind, pattern in CLAIMS:
        for match in pattern.finditer(answer):
            if kind == "form":
                name = _normalise(match.group("name"))
                grounded = name in evidence or name in loose
            else:
                nums = [n.replace(",", "") for n in re.split(r"\s?[–-]\s?", match.group("nums"))]
                grounded = all(
                    _number_is_grounded(n, kind, evidence) or float(n) in loose_numbers
                    for n in nums
                )
            text = match.group(0).strip()
            if not grounded and text not in flagged:
                flagged.append(text)
    return flagged


def verify_finding(finding: dict) -> list[str]:
    """Check one specialist's answer against what its searches actually returned."""
    problems = []
    answer, sources, steps = finding["answer"], finding["sources"], finding["steps"]
    if not any(step.tool == "search_regulations" for step in steps):
        problems.append("no search was performed, so the answer is not backed by any source")
    cited = {int(number) for number in CITATION.findall(answer)}
    unknown = sorted(number for number in cited if number not in sources)
    if unknown:
        problems.append(f"it cites source(s) {unknown} that no search returned")
    if sources and not cited:
        problems.append("sources were found but the answer cites none of them")
    def dump(step) -> str:
        return json.dumps(step.result, default=str, ensure_ascii=False)

    search_text = " ".join(dump(s) for s in steps if s.tool == "search_regulations")
    loose_text = " ".join(
        [finding.get("question", "")] + [dump(s) for s in steps if s.tool != "search_regulations"]
    )
    invented = ungrounded_claims(answer, search_text, loose_text)
    if invented:
        problems.append(
            "it states figures that appear in no source or tool result: "
            + ", ".join(invented)
        )
    return problems


def compose_answer(state: State) -> str:
    if state.get("declined"):
        return DECLINE_MESSAGE
    findings = [f for f in state.get("findings", []) if f]
    parts = []
    cited = {}
    offset = 0
    for finding in findings:
        sources = finding["sources"]

        def renumber(match, offset=offset, sources=sources):
            number = int(match.group(1))
            if number in sources:
                cited[number + offset] = sources[number]
                return f"[{number + offset}]"
            return match.group(0)

        # Each specialist cites its own sources as [1], [2]...; the code shifts them
        # so numbers never clash between specialists, whatever the model wrote.
        answer = CITATION.sub(renumber, finding["answer"])
        offset += max(sources, default=0)
        if len(findings) > 1:
            parts.append(f"**{SPECIALISTS[finding['agent']].title}**\n{answer}")
        else:
            parts.append(answer)
    text = "\n\n".join(parts)

    if cited:
        lines = [
            f"[{n}] {src['title']} (page {src['page']})" for n, src in sorted(cited.items())
        ]
        text += "\n\nSources:\n" + "\n".join(lines)

    if state.get("issues"):
        notes = "; ".join(
            f"{SPECIALISTS[i['agent']].title}: {', '.join(i['problems'])}"
            for i in state["issues"]
        )
        text += f"\n\nVerification notes (not fully resolved): {notes}."
    return text + "\n\n" + FOOTER


# ---------- model-calling pieces ----------

def _reasoning(model: str) -> dict:
    return {"reasoning_effort": "low"} if "gpt-oss" in model else {}


def _run_specialist(client, model, today, key, task, feedback=None) -> AgentResult:
    spec = SPECIALISTS[key]
    prompt = (
        SYSTEM_PROMPT
        + f"\n7. You are the {spec.title} specialist. Your documents cover "
        f"{spec.description}. Stay within them; another specialist covers other "
        "topics, so do not answer those yourself."
        "\n8. State only steps, fees, rates, day counts, timelines and form names "
        "that appear in your search results, and put a citation like [1] after every "
        "sentence or table row that states a fact. If the results do not give a "
        "procedure, fee, rate or deadline, say plainly that your documents do not "
        "state it. Never fill gaps from general knowledge. Cite only search results, "
        "never the results of calculate_fees or check_deadline: state those plainly."
    )
    if "check_deadline" in spec.tools:
        prompt += (
            "\n9. You know today's date. For 'how many days ago' or 'how many days "
            "remain', find the due-date rule by searching, then call check_deadline."
        )
    if feedback:
        task += (
            f"\n\nA reviewer found problems with your previous answer: {feedback}. "
            "Search again and fix them."
        )
    return run_agent(
        task,
        client=client,
        model=model,
        today=today,
        system_prompt=prompt,
        tools=[t for t in TOOLS if t["function"]["name"] in spec.tools],
        scope=list(spec.scope),
    )


def build_graph(client, model: str, today: date):
    from langgraph.graph import END, START, StateGraph

    def coordinate(state: State) -> dict:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COORDINATOR_PROMPT},
                {"role": "user", "content": state["question"]},
            ],
            temperature=0,
            max_completion_tokens=500,
            **_reasoning(model),
        )
        used = response.usage.total_tokens if response.usage else 0
        plan = parse_plan(response.choices[0].message.content or "")
        source = "model"
        if plan is None:
            plan, source = keyword_route(state["question"]), "fallback"
        subtasks, declined = plan
        return {
            "subtasks": subtasks,
            "declined": declined,
            "plan_source": source,
            "tokens": state.get("tokens", 0) + used,
        }

    def specialists(state: State) -> dict:
        subtasks = state["subtasks"]
        findings = list(state.get("findings") or [None] * len(subtasks))
        todo = state.get("rerun") or list(range(len(subtasks)))
        tokens = state.get("tokens", 0)
        feedback = state.get("feedback") or {}
        for index in todo:
            sub = subtasks[index]
            result = _run_specialist(
                client, model, today, sub["agent"], sub["task"], feedback.get(index)
            )
            tokens += result.tokens
            findings[index] = {
                "agent": sub["agent"],
                "task": sub["task"],
                "question": state["question"],
                "answer": result.answer,
                "sources": result.sources,
                "steps": result.steps,
            }
        return {"findings": findings, "tokens": tokens, "rerun": []}

    def verify(state: State) -> dict:
        issues = []
        for index, finding in enumerate(state["findings"]):
            problems = verify_finding(finding)
            if problems:
                issues.append({"index": index, "agent": finding["agent"],
                               "problems": problems})
        return {"issues": issues}

    def prepare_revision(state: State) -> dict:
        feedback = {i["index"]: "; ".join(i["problems"]) for i in state["issues"]}
        return {"rerun": list(feedback), "feedback": feedback,
                "revisions": state.get("revisions", 0) + 1}

    def compose(state: State) -> dict:
        return {"answer": compose_answer(state)}

    def after_coordinate(state: State) -> str:
        return "compose" if state.get("declined") else "specialists"

    def after_verify(state: State) -> str:
        if state.get("issues") and state.get("revisions", 0) < MAX_REVISIONS:
            return "revise"
        return "compose"

    graph = StateGraph(State)
    graph.add_node("coordinate", coordinate)
    graph.add_node("specialists", specialists)
    graph.add_node("verify", verify)
    graph.add_node("prepare_revision", prepare_revision)
    graph.add_node("compose", compose)
    graph.add_edge(START, "coordinate")
    graph.add_conditional_edges(
        "coordinate", after_coordinate,
        {"compose": "compose", "specialists": "specialists"},
    )
    graph.add_edge("specialists", "verify")
    graph.add_conditional_edges(
        "verify", after_verify,
        {"revise": "prepare_revision", "compose": "compose"},
    )
    graph.add_edge("prepare_revision", "specialists")
    graph.add_edge("compose", END)
    return graph.compile()


def run_team(question: str, client=None, model: str | None = None,
             today: date | None = None) -> TeamResult:
    import os

    if client is None:
        from groq import Groq

        client = Groq()
    model = model or os.environ["GROQ_MODEL"]
    today = today or date.today()
    final = build_graph(client, model, today).invoke(
        {"question": question, "tokens": 0, "revisions": 0}
    )
    return TeamResult(
        answer=final["answer"],
        subtasks=final.get("subtasks", []),
        findings=[f for f in final.get("findings", []) if f],
        issues=final.get("issues", []),
        revisions=final.get("revisions", 0),
        tokens=final.get("tokens", 0),
        plan_source=final.get("plan_source", "model"),
    )
