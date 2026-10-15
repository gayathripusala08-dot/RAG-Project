"""
Streamlit web page for the CBIT AI&DS syllabus assistant.

Run it from the project folder with:
    python -m streamlit run app.py

It uses the same engine as hybrid_router.py, so the projectapi
environment variable (your Groq API key) must be set.
"""

import contextlib
import io
import re
import threading

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Syllabus Assistant", page_icon="📚")

# ============================================================
# LOOK AND FEEL
# The page colours are set in .streamlit/config.toml.
# The CSS below only styles the blue banner and the buttons.
# ============================================================
st.markdown(
    """
<style>
/* the dark blue banner at the top */
.hero { background: #1B2A49; border-radius: 16px; padding: 28px 32px; margin-bottom: 24px; }
.hero .bar { width: 56px; height: 5px; background: #FFD84D; border-radius: 3px; margin-bottom: 16px; }
.hero h1 { color: #FFFFFF !important; margin: 0 0 8px 0 !important; padding: 0 !important; font-size: 2rem; }
.hero p { color: #C9D3E8; margin: 0; font-size: 1.05rem; }

/* the example question buttons */
.stButton > button { border-radius: 12px; border: 1px solid #D5DCEB; background: #FFFFFF; padding: 12px 16px; }
.stButton > button:hover { border-color: #2F5BEA; color: #2F5BEA; }
.stButton > button { height: auto; min-height: 3rem; }
.stButton > button p { white-space: normal; overflow: visible; text-overflow: clip; }

/* smaller banner on phones */
@media (max-width: 600px) {
    .hero { padding: 20px; }
    .hero h1 { font-size: 1.5rem; }
}
</style>
<div class="hero">
<div class="bar"></div>
<h1>Syllabus Assistant</h1>
<p>Ask about any CBIT AI&amp;DS subject: its topics, credits or semester.</p>
</div>
""",
    unsafe_allow_html=True,
)

# The search index and models take a while to load the first time.
try:
    with st.spinner("Loading syllabus data and models (first run only)..."):
        from hybrid_router import HELP_MESSAGE, NOT_FOUND_MESSAGE, NO_ROWS_MESSAGE, answer_question
except KeyError:
    st.error(
        "The projectapi environment variable (your Groq API key) is not set. "
        "Set it in your terminal, restart the terminal, and run the app again."
    )
    st.stop()

# ============================================================
# SETTINGS AND SMALL HELPERS
# ============================================================

EXAMPLES = [
    "What topics are covered in Data Structures?",
    "Which semester 3 subjects have more than 2 credits?",
    "What is the syllabus of DAA and how many credits does EDA have?",
    "What does Cloud Computing cover and in which semester is it taught?",
]

def load_subject_names():
    """Make a lookup like {"22CSC14N": "Design and Analysis of Algorithms"}."""
    try:
        table = pd.read_csv("subjects.csv")
        names = {}
        for code, title in zip(table["code"], table["title"]):
            nice = str(title).title().replace(" And ", " and ").replace(" Of ", " of ")
            names[str(code).upper()] = nice
        return names
    except Exception:
        return {}  # the page still works, it just shows the code only


SUBJECT_NAMES = load_subject_names()


@st.cache_resource
def get_engine_lock():
    """One lock shared by every browser session (the script itself re-runs on each click)."""
    return threading.Lock()


def friendly_error(message):
    """Turn a technical error into a short message a student can understand."""
    lowered = message.lower()
    if "429" in message or "rate limit" in lowered:
        return "The free LLM plan's limit has been reached. Please wait a while and try again."
    if "401" in message or "api key" in lowered or "api_key" in lowered:
        return "The API key is missing or invalid. Check the projectapi setting."
    return f"Something went wrong: {message}"


def ask(question):
    """Run one question through the engine and keep its printed log for display."""
    buffer = io.StringIO()
    answer, error = "", None
    try:
        # The engine prints its steps (captured below), so only one question runs at a time.
        with get_engine_lock(), contextlib.redirect_stdout(buffer):
            answer = answer_question(question)
    except Exception as e:
        error = str(e)

    log = buffer.getvalue().strip()
    match = re.search(r"\[Router decided: ([A-Z]+)", log)
    route = match.group(1) if match else "UNKNOWN"
    return {"question": question, "answer": answer, "route": route, "log": log, "error": error}


# ============================================================
# SHOWING AN ANSWER
# ============================================================

def split_source(text):
    """The answer starts with 'Source: <code>'. Return (code, the rest of the answer)."""
    match = re.match(r"\s*Source:\s*[\*\[`\s]*([A-Za-z0-9]+)[^\n]*\n", text)
    if match:
        return match.group(1).upper(), text[match.end():]
    return None, text


def show_text(text):
    """Show a written answer, with a small line saying which subject it came from."""
    code, body = split_source(text)
    if code:
        name = SUBJECT_NAMES.get(code)
        st.caption(f"Answered from {name} ({code})" if name else f"Answered from {code}")
    st.markdown(body.strip())


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
    elif answer == HELP_MESSAGE:
        st.write(answer)
    elif entry["route"] == "TABLE":
        st.code(answer, language=None)
    elif answer.startswith("From course content:") and marker in answer:
        docs, table = answer.split(marker, 1)
        st.markdown("**From the syllabus**")
        show_text(docs[len("From course content:"):].lstrip("\n"))
        st.markdown("**Subject details**")
        st.code(table, language=None)
    else:
        show_text(answer)



# ============================================================
# THE PAGE
# ============================================================

def use_example(text):
    st.session_state.pending = text


def clear_chat():
    st.session_state.history = []


if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar: a short guide and a button to start over.
with st.sidebar:
    st.header("What you can ask")
    st.write("- What a subject covers\n- Its credits and semester\n- Both in one question")
    st.write("Short names such as DAA, DBMS or OS work too.")
    st.button("Clear chat", on_click=clear_chat)
    st.caption(
        "Answers come from the syllabus file, so confirm anything important with "
        "the official document. This runs on a free LLM plan, so many questions "
        "in a row may show a limit message."
    )

# The chat box sits at the bottom of the page. A clicked example counts as a typed question.
typed = st.chat_input("Ask about a subject, e.g. DBMS")
question = st.session_state.pop("pending", None) or typed

# Before the first question, show a greeting and the example buttons.
if not st.session_state.history and not question:
    with st.chat_message("assistant", avatar="📚"):
        st.write("Hi! Ask me about any subject in the syllabus, or start with one of these.")
    columns = st.columns(2)
    for i, text in enumerate(EXAMPLES):
        columns[i % 2].button(
            text, key=f"example{i}", on_click=use_example, args=(text,), use_container_width=True
        )

# Earlier questions and answers.
for entry in st.session_state.history:
    with st.chat_message("user", avatar="🎓"):
        st.write(entry["question"])
    with st.chat_message("assistant", avatar="📚"):
        render(entry)

# The new question.
if question:
    with st.chat_message("user", avatar="🎓"):
        st.write(question)
    with st.chat_message("assistant", avatar="📚"):
        with st.spinner("Searching the syllabus..."):
            entry = ask(question)
        render(entry)
    st.session_state.history.append(entry)