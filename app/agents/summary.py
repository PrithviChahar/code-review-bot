"""Summary agent: plain-English explanation of the diff (M2). No JSON."""

from llm_client import RateLimitedError, chat_raw

SYSTEM_PROMPT = (
    "You are a senior engineer writing a short summary of a pull request for "
    "the author and reviewers. "
    "Explain in plain English, in 2-4 sentences, what the PR changes and why. "
    "Mention the main files touched and the purpose of the change. "
    "Do not list individual issues and do not output JSON — just prose."
)


def summarize(diff_text):
    user_content = f"Here is the pull request diff:\n\n{diff_text}"
    try:
        return chat_raw(SYSTEM_PROMPT, user_content)
    except RateLimitedError:
        return "Summary unavailable — the Groq API rate limit was hit during this run."
