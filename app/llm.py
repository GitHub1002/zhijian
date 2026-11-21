from langchain_core.prompts import ChatPromptTemplate
from openai import OpenAI

from . import config

_client = None
_PROMPT_TEMPLATE = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", "{user_prompt}"),
    ]
)


def get_client():
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    return _client


def _completion_messages(system_prompt, user_prompt):
    prompt_messages = _PROMPT_TEMPLATE.format_messages(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    return [
        {
            "role": "system" if message.type == "system" else "user",
            "content": message.content,
        }
        for message in prompt_messages
    ]


def generate(system_prompt, user_prompt):
    client = get_client()
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=_completion_messages(system_prompt, user_prompt),
        temperature=0.3,
    )
    return resp.choices[0].message.content


def generate_stream(system_prompt, user_prompt):
    client = get_client()
    stream = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=_completion_messages(system_prompt, user_prompt),
        temperature=0.3,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        token = chunk.choices[0].delta.content or ""
        if token:
            yield token
