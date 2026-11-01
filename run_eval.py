"""
Evaluation for the hybrid syllabus Q&A system.

Reads eval_questions.csv, runs every question through the real system,
and scores three things separately:

    1. Router     - did it pick the expected route (DOCUMENTS / TABLE / BOTH)?
    2. Retrieval  - did the system's retrieval (title match + document search)
                    rank the expected subject first (top 1), or at least
                    somewhere in its best three (top 3)? The embedding search
                    alone is also scored, as a baseline to compare against.
    3. Final answer - which subject did the written answer actually use?
    4. Table      - did the SQL return exactly the expected rows?

Each part is scored on its own, using the EXPECTED route, so one wrong
routing decision does not hide how well the other parts work.
Results are saved to eval_results.csv.
"""

import csv
import re
import sys
import time

import numpy as np

from hybrid_router import (
    answer_from_documents,
    answer_from_sql,
    codes,
    decide_route,
    doc_index,
    embed_model,
    expand_abbreviations,
    mentions_a_subject,
    retrieve_indices,
    scheme_courses,
    split_question,
)
from semester_summary import semester_reply

CODE_PATTERN = re.compile(r"\b\d{2}[A-Z]{2,5}\d{1,3}N?\b")
SOURCE_PATTERN = re.compile(r"Source:\s*[\*\[`\s]*([A-Za-z0-9]+)", re.IGNORECASE)
PAUSE_SECONDS = 5  # keeps us under the free API rate limit


def normalize_route(raw):
    """Same rule the real system uses to turn the router's reply into a route."""
    if re.search(r"\bOTHER\b", raw):
        return "OTHER"
    if "DOCUMENTS" in raw and "TABLE" not in raw:
        return "DOCUMENTS"
    if "TABLE" in raw and "DOCUMENTS" not in raw:
        return "TABLE"
    return "BOTH"


def retrieve_codes(question, k=3):
    """Codes of the k subjects the real system would show the LLM (title match + search), best first."""
    return [codes[i] for i in retrieve_indices(question, k)]


def faiss_only_codes(question, k=3):
    """Baseline for comparison: the embedding search alone, with no title matching."""
    vector = np.array(embed_model.encode([question])).astype("float32")
    _, indices = doc_index.search(vector, k)
    return [codes[i] for i in indices[0]]


def split_codes(text):
    return {c.strip() for c in text.split(";") if c.strip()}


def run_row(row):
    """Score one question. Returns a dict of results (True / False / None = not scored)."""
    # Same first step as the real system: spell out short forms and everyday
    # names (DAA, Data Structures) before anything else happens.
    question = expand_abbreviations(row["question"])
    expected_route = row["expected_route"]

    result = {"question": row["question"], "expected_route": expected_route}

    # 1. Router
    route = normalize_route(decide_route(question).upper())
    result["route"] = route
    result["route_ok"] = route == expected_route

    # For compound questions, split once and reuse for both paths
    if expected_route == "BOTH":
        doc_question, sql_question = split_question(question)
    else:
        doc_question = sql_question = question

    # 2. Retrieval (only when we know which subject is correct)
    expected_subject = row["expected_subject_code"].strip()
    if expected_subject and expected_subject != "NONE":
        ranked = retrieve_codes(doc_question, k=10)
        picked = ranked[:3]
        result["doc_question"] = doc_question
        result["retrieved"] = picked[0]
        result["top3"] = ";".join(picked)
        result["rank"] = ranked.index(expected_subject) + 1 if expected_subject in ranked else "10+"
        result["retrieval_ok"] = picked[0] == expected_subject
        result["top3_ok"] = expected_subject in picked
        result["top5_ok"] = expected_subject in ranked[:5]
        faiss_ranked = faiss_only_codes(doc_question, k=10)
        result["faiss_top1_ok"] = faiss_ranked[0] == expected_subject
        result["faiss_top3_ok"] = expected_subject in faiss_ranked[:3]
    else:
        result["retrieved"] = ""
        result["top3"] = ""
        result["retrieval_ok"] = None
        result["top3_ok"] = None
        result["top5_ok"] = None
        result["faiss_top1_ok"] = None
        result["faiss_top3_ok"] = None
        result["rank"] = ""

    # 2b. Final answer: which subject did the answer actually come from?
    # (expected_subject_code NONE means "no such subject, the answer should say so")
    if expected_subject:
        answer = answer_from_documents(doc_question)
        match = SOURCE_PATTERN.search(answer)
        source = match.group(1).upper() if match else "MISSING"
        result["final_source"] = source
        result["answer_start"] = answer[:90].replace("\n", " | ")
        result["final_ok"] = source == expected_subject
    else:
        result["final_source"] = ""
        result["answer_start"] = ""
        result["final_ok"] = None

    # 3. Table (only when we know the correct rows or value)
    expected_table = split_codes(row["expected_table_codes"])
    expected_text = row["expected_text"].strip()
    if expected_table or expected_text:
        # Same order as the real system: a whole-semester question is answered from the tables.
        output = semester_reply(sql_question, scheme_courses, mentions_a_subject)
        if output is None:
            output = answer_from_sql(sql_question)
        if expected_table:
            found = set(CODE_PATTERN.findall(output))
            result["table_found"] = ";".join(sorted(found))
            result["table_ok"] = found == expected_table
        else:
            result["table_found"] = ""
            result["table_ok"] = expected_text in output
    else:
        result["table_found"] = ""
        result["table_ok"] = None

    return result


def mark(value):
    if value is None:
        return "  -  "
    return "PASS " if value else "FAIL "


def percent(results, key):
    scored = [r[key] for r in results if r.get(key) is not None]
    if not scored:
        return "no questions scored"
    return f"{sum(scored)}/{len(scored)} = {100 * sum(scored) / len(scored):.0f}%"


class DailyLimitReached(Exception):
    """The free plan's daily token budget is used up. Retrying will not help."""


def run_row_safely(row):
    """Run one question. If the API fails, show why, wait, and try once more."""
    for attempt in (1, 2):
        try:
            return run_row(row)
        except Exception as e:
            if "tokens per day" in str(e) or "(TPD)" in str(e):
                raise DailyLimitReached(str(e))
            print(f"      !! error on '{row['question'][:50]}': {e}")
            if attempt == 1:
                print("      !! waiting 20 seconds, then trying once more")
                time.sleep(20)
    return {
        "question": row["question"],
        "expected_route": row["expected_route"],
        "route": "ERROR",
        "route_ok": None,
        "retrieval_ok": None,
        "top3_ok": None,
        "top5_ok": None,
        "final_ok": None,
        "table_ok": None,
    }


if __name__ == "__main__":
    # Usage:  python run_eval.py                     -> uses eval_questions.csv
    #         python run_eval.py eval_fresh_questions.csv   -> uses another question file
    questions_file = sys.argv[1] if len(sys.argv) > 1 else "eval_questions.csv"
    results_file = "eval_results.csv" if len(sys.argv) <= 1 else f"results_{questions_file}"

    with open(questions_file, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    print(f"Running {len(rows)} questions...\n")
    print("route  retr.  table  question")
    print("-" * 78)

    for row in rows:
        try:
            result = run_row_safely(row)
        except DailyLimitReached:
            print("\n!! STOPPED: the free daily token limit is used up, so the "
                  "remaining questions cannot run today.")
            print("!! Wait for the limit to reset, then run again. The scores "
                  f"below cover only the {len(results)} questions finished so far.")
            break
        results.append(result)
        print(
            f"{mark(result['route_ok'])} {mark(result.get('retrieval_ok'))} "
            f"{mark(result.get('table_ok'))} {result['question'][:60]}"
        )
        if result.get("retrieval_ok") is False:
            in_top3 = "IS" if result["top3_ok"] else "is NOT"
            print(f"      -> searched for: {result['doc_question']!r}")
            print(f"      -> top 3 picked: {result['top3'].replace(';', ', ')} | "
                  f"expected {row['expected_subject_code']} ({in_top3} in the top 3, "
                  f"ranked #{result['rank']})")
        if result.get("final_ok") is False:
            print(f"      -> final answer used {result['final_source']}, "
                  f"expected {row['expected_subject_code']}")
            print(f"      -> answer began: {result['answer_start']}")
        if result.get("table_ok") is False:
            expected = row["expected_table_codes"] or row["expected_text"]
            print(f"      -> table returned {result.get('table_found') or '(nothing)'}, "
                  f"expected {expected}")
        time.sleep(PAUSE_SECONDS)

    print("\n" + "=" * 78)
    print("Router accuracy   :", percent(results, "route_ok"))
    print("Retrieval (top 1) :", percent(results, "retrieval_ok"))
    print("Retrieval (top 3) :", percent(results, "top3_ok"))
    print("Retrieval (top 5) :", percent(results, "top5_ok"))
    print("   (for comparison, embedding search alone: top 1 "
          f"{percent(results, 'faiss_top1_ok')} | top 3 {percent(results, 'faiss_top3_ok')})")
    print("Final answer used the right subject:", percent(results, "final_ok"))
    print("Table accuracy    :", percent(results, "table_ok"))

    fields = [
        "question", "expected_route", "route", "route_ok",
        "doc_question", "retrieved", "retrieval_ok", "top3", "top3_ok", "rank",
        "faiss_top1_ok", "faiss_top3_ok",
        "final_source", "final_ok", "answer_start", "table_found", "table_ok",
    ]
    def save(filename):
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)

    try:
        save(results_file)
        print(f"\nDetails saved to {results_file}")
    except PermissionError:
        backup_file = results_file.replace(".csv", "_new.csv")
        save(backup_file)
        print(f"\n{results_file} is open in another program, so the details "
              f"were saved to {backup_file} instead")