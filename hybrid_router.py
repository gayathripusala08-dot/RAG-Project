"""
Syllabus Question-Answering System (Hybrid RAG + Text-to-SQL)

Answers natural-language questions about college subjects by routing each
question to the most suitable data source:

    1. Unstructured syllabus content -> semantic search (FAISS, top 5) + LLM
       that picks the matching subject and cites it as 'Source: <code>'
    2. Structured subject data       -> LLM-generated SQL executed on SQLite
    3. Compound questions            -> split into sub-questions, both paths used

Required input files:
    syllabus_content.csv  (columns: code, content)
    subjects.csv          (columns: code, title, semester, credits)

Required environment variable:
    projectapi   (your Groq API key)
"""

import difflib
import os
import re
import sqlite3

import faiss
import numpy as np
import pandas as pd
from groq import Groq
from sentence_transformers import SentenceTransformer

# ============================================================
# CONFIGURATION AND INITIALIZATION
# ============================================================

LLM_MODEL = "openai/gpt-oss-20b"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Short forms students use, and the full subject name each one stands for.
# Add more here. Leave out short forms that could mean two subjects.
# The full name must match the title in subjects.csv (case does not matter).
ABBREVIATIONS = {
    "DAA": "Design and Analysis of Algorithms",
    "EDA": "Exploratory Data Analysis and Visualization",
    "DBMS": "Database Management Systems",
    "OS": "Operating Systems",
    "CN": "Computer Networks",
    "NLP": "Natural Language Processing with Transformers",
    "PPL": "Principles of Programming Languages",
    "FLCD": "Formal Language Theory and Compiler Design",
    "RL": "Reinforcement Learning",
    "BDA": "Principles of Big Data Analytics",
    "MSF": "Mathematical and Statistical Foundations",
    "DM": "Discrete Mathematics",
    "RPA": "Robotic Process Automation",
    "XAI": "Explainable Artificial Intelligence (XAI)",
    "ML": "Fundamentals of Machine Learning",
    "CC": "Cloud Computing",
}

# Everyday names students use for subjects whose official title is longer or
# worded differently. Same rule as above: the full name must match a title
# in subjects.csv.
ALIASES = {
    "Data Structures": "Data Structures using C++",
    "Machine Learning": "Fundamentals of Machine Learning",
    "Explainable Artificial Intelligence": "Explainable Artificial Intelligence (XAI)",
}

# Short forms are also built automatically from the subject titles (ICFP, DLCA, ...).
# Words that are skipped when taking the first letters of a title:
SMALL_WORDS = {"and", "of", "to", "the", "for", "in", "with", "using", "on", "a", "an"}
# Automatic short forms that are also everyday words or names, so they are never expanded:
BLOCKED_SHORT_FORMS = {"ITS", "IIT", "CSE"}

# What the assistant says to a greeting or to text that is not about subjects.
HELP_MESSAGE = (
    "Hi! How can I help you? Ask me about any subject in the CBIT AI&DS syllabus: "
    "what it covers, its credits, or which semester it is in. "
    'For example: "What does Cloud Computing cover?" or "Credits for DBMS".'
)
GREETING_PATTERN = re.compile(
    r"(hi+|hello+|hey+|hai|hlo|helo|yo|sup|namaste|ok|okay|thanks|thank you|thankyou|bye|help|"
    r"good (morning|afternoon|evening|night)|how are you|who are you|what can you do)",
    re.IGNORECASE,
)

NO_ROWS = "No matching rows found."  # what the SQL path returns for an empty result
NOT_FOUND_MESSAGE = (
    "I couldn't find that subject in the CBIT AI&DS syllabus. "
    "Please check the spelling or try the full subject name."
)
NO_ROWS_MESSAGE = (
    "Sorry, I couldn't find any subject matching that. Try the full subject "
    "name or a short form like DBMS, or check the spelling."
)

# The API key is read from the environment so it is never stored in the code.
#   Windows (PowerShell): $env:projectapi="your_key"
#   macOS / Linux:        export projectapi="your_key"
client = Groq(api_key=os.environ["projectapi"])

# --- Unstructured data: load syllabus content and build a vector index ---
doc_df = pd.read_csv("syllabus_content.csv")
titles_df = pd.read_csv("subjects.csv")[["code", "title"]]
doc_df = doc_df.merge(titles_df, on="code", how="left")
doc_df["title"] = doc_df["title"].fillna("")

codes = doc_df["code"].tolist()
titles = doc_df["title"].tolist()
contents = doc_df["content"].tolist()
# The title is part of the searched text, so a question that names a
# subject can match it directly.
documents = (doc_df["title"] + ". " + doc_df["content"]).tolist()

embed_model = SentenceTransformer(EMBEDDING_MODEL)
document_vectors = np.array(embed_model.encode(documents)).astype("float32")

doc_index = faiss.IndexFlatL2(document_vectors.shape[1])
doc_index.add(document_vectors)

# --- Structured data: load subject records into an in-memory SQLite database ---
sql_df = pd.read_csv("subjects.csv")
# check_same_thread=False lets the web page (which runs each request on its own
# thread) use this connection. It is only read from, never written to.
conn = sqlite3.connect(":memory:", check_same_thread=False)
sql_df.to_sql("subjects", conn, index=False, if_exists="replace")

def make_short_form(title):
    """First letters of a title, e.g. 'INDIAN CONSTITUTION AND FUNDAMENTAL PRINCIPLES' -> 'ICFP'."""
    title = re.sub(r"\(.*?\)", "", title)  # ignore things like (XAI)
    words = [w for w in re.findall(r"[A-Za-z0-9]+", title) if w.lower() not in SMALL_WORDS]
    return "".join(w[0] for w in words).upper()


def build_auto_short_forms():
    """
    Make a short form for every theory subject, e.g. {'ICFP': 'INDIAN CONSTITUTION ...'}.

    A short form is skipped if it is shorter than 3 letters, if two subjects would
    share it (it would be a guess), or if it is in BLOCKED_SHORT_FORMS.
    """
    found = {}
    for title in titles_df["title"]:
        title = str(title)
        if title.upper().endswith(" LAB"):
            continue  # a student types the short form plus 'lab', e.g. 'dbms lab'
        found.setdefault(make_short_form(title), []).append(title)
    return {
        short: names[0]
        for short, names in found.items()
        if len(short) >= 3 and len(names) == 1 and short not in BLOCKED_SHORT_FORMS
    }


AUTO_SHORT_FORMS = build_auto_short_forms()

# Startup check: every abbreviation must point to an exact title in subjects.csv,
# otherwise the title match in the document path cannot find it.
_all_titles = {t.lower() for t in titles_df["title"]}
for _short, _full in {**ABBREVIATIONS, **ALIASES}.items():
    if _full.lower() not in _all_titles:
        print(f"[WARNING] {_short} -> '{_full}' is not an exact title in subjects.csv")


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def ask_llm(prompt):
    """Send a single-turn prompt to the LLM and return the stripped response text."""
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,  # same question -> same answer, which keeps the evaluation steady
    )
    return response.choices[0].message.content.strip()


def clean_sql(raw):
    """Remove Markdown code fences and trailing semicolons from LLM-generated SQL."""
    sql = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).replace("```", "")
    return sql.strip().rstrip(";").strip()


def is_safe_select(sql):
    """
    Validate that the query is a single, read-only SELECT statement.

    Guards against destructive or multi-statement queries, since the SQL
    is generated by an LLM and executed directly.
    """
    lowered = sql.lower()
    if not lowered.startswith("select"):
        return False
    if ";" in lowered:  # reject stacked statements
        return False
    banned = ["insert", "update", "delete", "drop", "alter", "create", "attach", "pragma"]
    return not any(re.search(rf"\b{word}\b", lowered) for word in banned)


def _inside_known_title(text, start, end):
    """True if text[start:end] sits inside a full subject title that appears in text."""
    lowered = text.lower()
    for title in _all_titles:
        pos = lowered.find(title)
        while pos != -1:
            if pos <= start and end <= pos + len(title):
                return True
            pos = lowered.find(title, pos + 1)
    return False


def expand_abbreviations(question):
    """
    Replace short forms (like DAA) and everyday names (like Data Structures)
    with the official subject title.

    A match that is already part of a full title is left alone, so a title the
    student typed in full is never expanded twice.
    """
    for short, full in {**AUTO_SHORT_FORMS, **ABBREVIATIONS, **ALIASES}.items():
        def replace(match, full=full):
            if _inside_known_title(match.string, match.start(), match.end()):
                return match.group(0)
            return full

        question = re.sub(rf"\b{re.escape(short)}\b", replace, question, flags=re.IGNORECASE)
    return _fix_alias_typos(question)


def _fix_alias_typos(question, cutoff=0.9):
    """
    Catch small spelling mistakes in everyday names, e.g. 'Machin Learning'.

    Slides a window with the same number of words as each alias over the
    question. If the window is almost (but not exactly) the alias, it is
    replaced by the official title. Only the ALIASES are checked this way;
    short forms like DM are too short to match safely by similarity.
    """
    for short, full in ALIASES.items():
        n = len(short.split())
        words = list(re.finditer(r"[A-Za-z0-9+&]+", question))
        for i in range(len(words) - n + 1):
            start, end = words[i].start(), words[i + n - 1].end()
            window = question[start:end]
            if window.lower() == short.lower() or _inside_known_title(question, start, end):
                continue
            if difflib.SequenceMatcher(None, window.lower(), short.lower()).ratio() >= cutoff:
                question = question[:start] + full + question[end:]
                break
    return question


def doc_not_found(answer):
    """True if the document answer says no subject matched ('Source: NONE')."""
    return re.match(r"\W*source:\s*\W*none\b", answer, flags=re.IGNORECASE) is not None


def is_not_a_question(text):
    """True for a greeting ('hi', 'hello') or text with no real words ('???', '12345')."""
    cleaned = re.sub(r"[^\w\s]", "", text).strip()
    if not re.search(r"[A-Za-z]", cleaned):
        return True
    return GREETING_PATTERN.fullmatch(cleaned) is not None


def find_title_matches(question):
    """
    Return indices of subjects whose full title appears in the question.

    Longest titles come first, so a question that says '... Lab' ranks the lab
    ahead of its theory course, while a question without 'Lab' only matches
    the theory course.
    """
    q = question.lower()
    hits = [i for i, t in enumerate(titles) if t and t.lower() in q]
    return sorted(hits, key=lambda i: len(titles[i]), reverse=True)


# ============================================================
# ANSWERING PATHS
# ============================================================

def build_document_prompt(question, indices):
    """
    Build the prompt for the document path from the top-ranked subjects.

    Every candidate is labelled with its subject code and title, so the LLM
    can tell which entry matches the subject the question is about.
    """
    entries = [f"[{codes[i]}] {titles[i]}\n{contents[i]}" for i in indices]
    context = "\n\n".join(entries)
    return (
        "Below are syllabus entries for different subjects. Each entry starts "
        "with its subject code and title.\n\n"
        f"{context}\n\n"
        "Answer the question using ONLY the entry whose subject matches the "
        "question. If the question names several subjects (for example to "
        "compare them), use the entry of each subject it names. If the question "
        "does not mention a lab, prefer the theory course over its lab. "
        "If none of the entries is about the subject asked, reply with the "
        "first line 'Source: NONE' and then say the subject was not found. "
        "Otherwise the first line of your reply must be exactly "
        "'Source: <subject code>' (for several subjects: 'Source: <code>, <code>'), "
        "followed by the answer.\n\n"
        f"Question: {question}"
    )


def retrieve_indices(question, k=5):
    """
    Pick the k syllabus entries to show the LLM, best first.

    Subjects whose full title appears in the question go first, and the
    semantic (FAISS) search fills the remaining slots.
    """
    query_vector = np.array(embed_model.encode([question])).astype("float32")
    _, faiss_indices = doc_index.search(query_vector, k)

    indices = list(find_title_matches(question))
    for i in faiss_indices[0]:
        if i not in indices:
            indices.append(i)
    return indices[:k]


def answer_from_documents(question, k=5):
    """
    Answer a content-related question using retrieval-augmented generation.

    The LLM sees the entries picked by retrieve_indices and chooses the one
    that matches the subject asked about. The reply starts with a
    'Source: <code>' line, so every answer names its subject.
    """
    indices = retrieve_indices(question, k)
    print(f"[Retrieved: {[codes[i] for i in indices]}]")  # kept for debugging
    return ask_llm(build_document_prompt(question, indices))


def answer_from_sql(question):
    """
    Answer a data-related question by generating and executing SQL.

    The generated query is cleaned and validated as a read-only SELECT
    before execution. Identifying columns are included in the result so
    that multiple matches (e.g., a course and its lab) remain distinguishable.
    """
    sql_prompt = (
        "The table 'subjects' has columns: code, title, semester, credits. "
        "semester is stored as Roman numerals (I, II, III...), not numbers. "
        "title values are UPPERCASE; match subject names with "
        "UPPER(title) LIKE '%NAME%'. "
        "If the question names a specific subject, ALWAYS filter on that "
        "subject's title with a WHERE clause. "
        "ALWAYS match subject names with LIKE, never =, so a course and its lab "
        "are both returned. Use the full subject name inside the LIKE pattern, "
        "never a shortened part of it. "
        "NEVER use SUM, COUNT or AVG unless the question explicitly asks for a "
        "total or a count across many subjects. A question like 'how many "
        "credits is X worth' only needs the matching rows, not a total. "
        "Unless the question asks to count or sum, ALWAYS select all four "
        "columns: code, title, semester, credits, so every row can be identified. "
        "Write ONLY a single SQL SELECT query (no explanation, no markdown) "
        f"to answer: {question}"
    )
    generated_sql = clean_sql(ask_llm(sql_prompt))
    print(f"[SQL: {generated_sql}]")  # kept so you can see what was run

    if not is_safe_select(generated_sql):
        return "Blocked: the generated query was not a safe, read-only SELECT."

    try:
        result = pd.read_sql_query(generated_sql, conn)
        if result.empty:
            return NO_ROWS
        return result.to_string(index=False)
    except Exception as e:
        return f"SQL execution failed: {e}"


# ============================================================
# ROUTING LOGIC
# ============================================================

def split_question(question):
    """
    Decompose a compound question into two self-contained sub-questions.

    Returns a (document_question, table_question) tuple. Each sub-question
    must restate the subject name explicitly (no pronouns), otherwise the
    SQL generator loses context and may aggregate across all subjects.
    Falls back to the original question if the response cannot be parsed.
    """
    split_prompt = (
        "Split this question into two separate, focused questions:\n"
        "1. A question about course TOPICS/CONTENT only\n"
        "2. A question about NUMBERS/DATA (credits, semester, etc.) only\n\n"
        "Rules: each question must be fully self-contained. Never use pronouns "
        "like 'it' or 'that subject'; always repeat the full subject name.\n\n"
        f"Original question: {question}\n\n"
        "Reply in EXACTLY this format, nothing else:\n"
        "DOCUMENT_QUESTION: <question here>\n"
        "TABLE_QUESTION: <question here>"
    )
    text = ask_llm(split_prompt)

    doc_question = question  # fallback if parsing fails
    sql_question = question
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("DOCUMENT_QUESTION:"):
            doc_question = line.split(":", 1)[1].strip()
        elif line.startswith("TABLE_QUESTION:"):
            sql_question = line.split(":", 1)[1].strip()

    return doc_question, sql_question


def decide_route(question):
    """
    Classify which data source(s) a question requires.

    Returns one of: DOCUMENTS, TABLE, BOTH, or OTHER (not about college subjects).
    """
    router_prompt = (
        "You are deciding how to answer a question about college subjects. "
        "There are two data sources:\n"
        "1. DOCUMENTS - contains topic/unit content for each subject (use for "
        "questions about what a subject covers, teaches, or includes)\n"
        "2. TABLE - contains code, title, semester, credits (use for questions "
        "involving filtering, counting, comparing numbers, or semester)\n\n"
        "If the question is not about college subjects at all (a greeting, small "
        "talk, random letters, or general knowledge), the answer is OTHER. A "
        "question asking whether a subject exists IS about college subjects.\n\n"
        f"Question: {question}\n\n"
        "Reply with ONLY one word: DOCUMENTS, TABLE, BOTH, or OTHER."
    )
    return ask_llm(router_prompt).upper()


def answer_question(question):
    """
    Main entry point: route the question and return the combined answer.

    Short forms like DAA are expanded first. If the subject asked about does
    not exist, a clear 'not found' message is returned instead of raw
    'NONE' or 'no rows' output. Unrecognized routing output is treated as
    BOTH, so that neither data source is skipped when the classifier is
    uncertain.
    """
    if is_not_a_question(question):
        print("[Router decided: OTHER]")
        return HELP_MESSAGE

    expanded = expand_abbreviations(question)
    if expanded != question:
        print(f"[Expanded short forms -> '{expanded}']")
        question = expanded

    route = decide_route(question)
    print(f"[Router decided: {route}]")

    if re.search(r"\bOTHER\b", route):
        return HELP_MESSAGE

    if "DOCUMENTS" in route and "TABLE" not in route:
        answer = answer_from_documents(question)
        return NOT_FOUND_MESSAGE if doc_not_found(answer) else answer

    if "TABLE" in route and "DOCUMENTS" not in route:
        answer = answer_from_sql(question)
        return NO_ROWS_MESSAGE if answer == NO_ROWS else answer

    doc_question, sql_question = split_question(question)
    print(f"[Split into -> DOCS: '{doc_question}' | TABLE: '{sql_question}']")
    doc_answer = answer_from_documents(doc_question)
    sql_answer = answer_from_sql(sql_question)

    docs_missing = doc_not_found(doc_answer)
    if docs_missing and sql_answer == NO_ROWS:
        return NOT_FOUND_MESSAGE
    if docs_missing:
        doc_answer = "No syllabus content was found for this subject."
    return f"From course content:\n{doc_answer}\n\nFrom subject data:\n{sql_answer}"


# ============================================================
# DEMONSTRATION
# ============================================================

if __name__ == "__main__":
    test_questions = [
        "What topics are covered in Data Structures?",                         # document route
        "Which semester 3 subjects have more than 2 credits?",                 # table route
        "What does Data Structures cover, and how many credits is it worth?",  # combined route
    ]

    for q in test_questions:
        print("=" * 60)
        print("Question:", q)
        print(answer_question(q))
        print()