"""Chair (Leader) prompts for event-driven Agora discussions.

The chair is the team Leader, who:
  1. Opens the discussion (states topic, names first speaker)
  2. Evaluates after each speaker (continue? vote? close?)
  3. Summarizes and closes

All chair outputs are JSON for machine parsing by the driver.
"""
from __future__ import annotations


# --- Opening ---------------------------------------------------------------

CHAIR_OPENING_PROMPT = """\
You are chairing an Agora team discussion.

TOPIC: {title}
DESCRIPTION: {description}
PARTICIPANTS: {participants}
TASK CONTEXT:
{task_context}

Open the discussion:
1. Briefly state the topic and why it matters.
2. Name the first speaker (must be one of: {participants}).
3. Ask them a guiding question to kick off.

Respond with JSON ONLY (no markdown, no prose before or after):
{{
  "opening": "<2-3 sentences opening statement>",
  "next_speaker": "<profile_name from participants>",
  "guidance": "<specific question for the first speaker>"
}}
"""


# --- Evaluate after each speaker -------------------------------------------

CHAIR_EVALUATE_PROMPT = """\
You are chairing an Agora team discussion.

TOPIC: {title}
PARTICIPANTS: {participants}

DISCUSSION SO FAR:
{discussion_history}

EVALUATE the discussion state:
- Have all participants spoken at least once? If not, continue.
- Are there unresolved disagreements? If yes and stuck, call a vote.
- Has enough been said to reach a conclusion? If yes, close.
- Is someone going off-topic? If yes, redirect with guidance.
- Do you need more information (web search, code reading, test results)?
  If yes, dispatch a specific participant to gather it.

Respond with JSON ONLY:
{{
  "action": "continue" | "dispatch" | "vote" | "close",
  "next_speaker": "<profile_name or null>",
  "guidance": "<question/redirection for next speaker, or null>",
  "dispatch_task": "<specific investigation task for the dispatched participant, or null>",
  "reason": "<1 sentence why you chose this action>"
}}

Rules:
- "continue": pick the next speaker and optionally guide them.
- "dispatch": send a participant to investigate (web search, read code, run tests).
  Set next_speaker to the investigator, dispatch_task to the specific task.
  The investigator will use their tools and report findings.
- "vote": call a formal vote if the discussion is deadlocked.
- "close": the discussion is ready to summarize.

CRITICAL — Avoid false truncation calls:
- A speaker's response is NOT truncated if it ends with a sentence-ending
  punctuation mark (. ! ? : ) or a closing delimiter (}} ] ) ```) or an emoji.
  Do NOT claim truncation for responses that end naturally.
- Only flag truncation if the text breaks mid-word or mid-sentence with NO
  punctuation and reads as an obvious cut-off.
- If a speaker repeats similar points across turns, that is redundancy, NOT
  truncation. Move the discussion forward instead of asking them to "finish".
- Never retry the same speaker more than 2 consecutive times for the same
  reason. If their answer is adequate (even if imperfect), advance to the
  next participant or call a vote.
"""


# --- Voting ----------------------------------------------------------------

CHAIR_VOTE_CALL_PROMPT = """\
You are chairing an Agora discussion. It's time to vote.

TOPIC: {title}
DISCUSSION SUMMARY:
{discussion_history}

State clearly what is being voted on, then ask each participant to vote.
Keep it to 2-3 sentences.
"""


# --- Summary ---------------------------------------------------------------

CHAIR_SUMMARY_PROMPT = """\
You are chairing an Agora discussion. The discussion is now closed.

TOPIC: {title}
FULL DISCUSSION:
{discussion_history}

{vote_summary}

Generate a structured summary. Respond with JSON ONLY:
{{
  "summary": "<2-3 sentence summary of the discussion>",
  "action_items": [
    {{"item": "<description>", "owner": "<role>", "depends_on": []}}
  ],
  "confidence": 0.0,
  "decision": "adopted" | "rejected" | "no_consensus"
}}

For action_items:
- owner must be one of: {participants}
- depends_on is a list of 1-based indices into action_items (item N must complete before this one)
- Use [] if no dependency

For decision:
- "adopted": consensus reached, proceed with the plan
- "rejected": discussion showed the approach is wrong
- "no_consensus": unresolved disagreement, Leader decides
"""


# --- Speaker prompt builder ------------------------------------------------

def build_speaker_prompt(
    role: str,
    title: str,
    description: str,
    discussion_history: str,
    guidance: str,
    task_context: str = "",
) -> str:
    """Build the prompt for a participant's turn to speak."""
    parts = [
        f"You are **{role}** participating in an Agora team discussion.",
        "",
        f"## Topic\n{title}",
        "",
    ]
    if description:
        parts.append(f"## Description\n{description}")
        parts.append("")
    if task_context:
        parts.append(f"## Task Context\n{task_context[:2000]}")
        parts.append("")
    if discussion_history:
        parts.append(f"## Discussion So Far\n{discussion_history}")
        parts.append("")
    if guidance:
        parts.append(f"## Leader's Guidance\n{guidance}")
        parts.append("")
    parts.append(
        "## Your Turn\n"
        "Speak from your professional perspective. You may:\n"
        "- Reference other speakers: \"I agree with [name] that...\" or \"I disagree with [name]...\"\n"
        "- Use your tools (read_file, web_search, terminal, etc.) to gather information\n"
        "- Change your stance from a previous round if new information warrants it\n"
        "\n"
        "Keep it concise (2-4 paragraphs). Be specific and actionable.\n"
        "\n"
        f"After your analysis, output your speech on a new line starting with:\n"
        "DISCUSSION_REPLY: <your speech>"
    )
    return "\n".join(parts)


def build_vote_prompt(
    role: str,
    title: str,
    discussion_history: str,
) -> str:
    """Build the prompt for a participant to cast their vote."""
    return (
        f"You are **{role}** in an Agora discussion. It's time to vote.\n"
        f"\n"
        f"## Topic\n{title}\n"
        f"\n"
        f"## Discussion\n{discussion_history}\n"
        f"\n"
        f"Cast your vote. Respond with JSON ONLY:\n"
        f'{{"vote": "adopt" | "reject" | "abstain", "reason": "<1-2 sentences>"}}\n'
    )
