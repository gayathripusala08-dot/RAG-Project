"""
Web server for the CBIT AI&DS syllabus assistant.

The page itself is plain HTML + CSS (templates/index.html and static/style.css).
This file is the small Python server behind it: it receives the question from
an HTML form, runs it through the same engine as hybrid_router.py, and sends
the page back with the answer filled in.

Run it from the project folder with:
    python -m uvicorn server:app

then open http://127.0.0.1:8000 in your browser.
Needs the GROQ_API_KEY environment variable, like hybrid_router.py.
"""

import contextlib
import html
import io
import re
import threading
from pathlib import Path

import markdown
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Loading the engine builds the search index and loads the models (takes a while).
try:
    from hybrid_router import answer_question
except KeyError:
    raise SystemExit(
        "GROQ_API_KEY is not set. Set it with setx, open a NEW terminal, "
        "and run the server again."
    )

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Syllabus Assistant")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# The engine prints its steps and shares one database connection, so only one
# question is processed at a time. Fine for a demo used by one person.
engine_lock = threading.Lock()

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


def to_html(text):
    """
    Turn the LLM's Markdown (bold, bullets, tables) into HTML.

    The text is escaped first, so any HTML tags inside it are shown as plain
    text and can never run in the browser.
    """
    text = re.sub(r"^\s*(Source:[^\n]*)\n", r"**\1**\n\n", text)  # bold the citation line
    return markdown.markdown(html.escape(text, quote=False), extensions=["tables"])


def run_engine(question):
    """Run one question and capture the steps the engine prints."""
    buffer = io.StringIO()
    answer, error = "", None
    with engine_lock:
        try:
            with contextlib.redirect_stdout(buffer):
                answer = answer_question(question)
        except Exception as e:
            error = str(e)
    return answer, buffer.getvalue().strip(), error


def build_result(question):
    """Run the question and arrange the answer into parts the template can show."""
    answer, log, error = run_engine(question)
    match = re.search(r"\[Router decided: ([A-Z]+)", log)
    route = match.group(1) if match else "UNKNOWN"

    result = {"route": route, "log": log, "error": None, "details": None, "parts": []}
    if error:
        result["error"] = friendly_error(error)
        result["details"] = error
        return result

    marker = "\n\nFrom subject data:\n"
    if route == "TABLE":
        result["parts"] = [{"title": None, "text": answer}]
    elif answer.startswith("From course content:") and marker in answer:
        docs, table = answer.split(marker, 1)
        docs = docs[len("From course content:"):].lstrip("\n")
        result["parts"] = [
            {"title": "From course content", "html": to_html(docs)},
            {"title": "From subject data", "text": table},
        ]
    else:
        result["parts"] = [{"title": None, "html": to_html(answer)}]
    return result


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    context = {"examples": EXAMPLES, "question": "", "result": None}
    return templates.TemplateResponse(request, "index.html", context)


@app.post("/ask", response_class=HTMLResponse)
def ask(request: Request, question: str = Form(...)):
    question = question.strip()[:300]
    result = build_result(question) if question else None
    context = {"examples": EXAMPLES, "question": question, "result": result}
    return templates.TemplateResponse(request, "index.html", context)