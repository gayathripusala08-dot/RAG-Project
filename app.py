"""
Streamlit web page for the CBIT AI&DS syllabus assistant.

Run it from the project folder with:
    python -m streamlit run app.py

It uses the same engine as hybrid_router.py, so the GROQ_API_KEY
environment variable must be set.
"""

import contextlib
import io
import re

import streamlit as st

st.set_page_config(page_title="Syllabus Assistant", page_icon="📚")
st.title("📚 CBIT AI&DS Syllabus Assistant")
st.caption(
    "Ask about topics, credits or semesters. Answers come from the syllabus; "
    "please confirm anything important with the official document."
)

# The search index and models take a while to load the first time.
try:
    with st.spinner("Loading syllabus data and models (first run only)..."):
        from hybrid_router import NOT_FOUND_MESSAGE, NO_ROWS_MESSAGE, answer_question
except KeyError:
    st.error(
        "GROQ_API_KEY is not set. Set it in your terminal, restart the "
        "terminal, and run the app again."
    )
    st.stop()

EXAMPLES = [
    "What topics are covered in Data Structures?",
    "Which semester 3 subjects have more than 2 credits?",
    "What does Cloud Computing cover and in which semester is it taught?",
]


def friendly_error(message):
    """Turn a technical error into a short message a student can understand."""
    lowered = message.lower()
    if "429" in message or "rate limit" in lowered:
        return "The free LLM plan's limit has been reached. Please wait a while and try again."
    if "401" in message or "api key" in lowered or "api_key" in lowered:
        return "The API key is missing or invalid. Check the GROQ_API_KEY setting."
    return f"Something went wrong: {message}"


def ask(question):
    """Run one question through the engine and keep its printed log for display."""
    buffer = io.StringIO()
    answer, error = "", None
    try:
        with contextlib.redirect_stdout(buffer):
            answer = answer_question(question)
    except Exception as e:
        error = str(e)

    log = buffer.getvalue().strip()
    match = re.search(r"\[Router decided: ([A-Z]+)", log)
    route = match.group(1) if match else "UNKNOWN"
    return {"question": question, "answer": answer, "route": route, "log": log, "error": error}


def format_source(text):
    """Make the 'Source: <code>' first line bold and separate it from the answer."""
    return re.sub(r"^\s*(Source:[^\n]*?)\s*\n", r"**\1**\n\n", text)


def render(entry):
    """Show one answer: text answers as formatted text, table results as a table."""
    if entry["error"]:
        st.error(friendly_error(entry["error"]))
        with st.expander("Technical details (copy this if you need help)"):
            st.code(entry["error"], language=None)
            if entry["log"]:
                st.code(entry["log"], language=None)
        return

    answer = entry["answer"]
    marker = "\n\nFrom subject data:\n"

    if answer in (NOT_FOUND_MESSAGE, NO_ROWS_MESSAGE):
        st.info(answer)
    elif entry["route"] == "TABLE":
        st.code(answer, language=None)
    elif answer.startswith("From course content:") and marker in answer:
        docs, table = answer.split(marker, 1)
        st.markdown("**From course content**")
        st.markdown(format_source(docs[len("From course content:"):].lstrip("\n")))
        st.markdown("**From subject data**")
        st.code(table, language=None)
    else:
        st.markdown(format_source(answer))

    with st.expander("How this was answered"):
        st.write(f"Route chosen: **{entry['route']}**")
        st.code(entry["log"] or "(no details)", language=None)


def use_example(text):
    st.session_state.pending = text


with st.sidebar:
    st.header("Try an example")
    for text in EXAMPLES:
        st.button(text, on_click=use_example, args=(text,), use_container_width=True)
    st.caption(
        "This runs on a free LLM plan. If many questions are asked quickly, "
        "a limit message may appear."
    )

if "history" not in st.session_state:
    st.session_state.history = []

for entry in st.session_state.history:
    with st.chat_message("user"):
        st.write(entry["question"])
    with st.chat_message("assistant"):
        render(entry)

typed = st.chat_input("Ask about a subject...")
question = st.session_state.pop("pending", None) or typed

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            entry = ask(question)
        render(entry)
    st.session_state.history.append(entry)