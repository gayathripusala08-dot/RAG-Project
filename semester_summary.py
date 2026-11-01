"""
Semester summaries: the subjects and the credit total of a whole semester.

Why this file exists
--------------------
subjects.csv has one row for every elective OPTION, but a student takes only
ONE subject from each elective group (for example one of the five Professional
Elective-5 subjects). Listing every row, or adding up every row, gives a wrong
semester. Here every elective group is shown as a choice and counted once.

Data files (both in the project folder):
    subjects.csv   code, title, semester, credits
    electives.csv  code, slot, title, semester, credits
                   - an elective option: its code and slot ('Open Elective-2', ...)
                   - a scheme item with no syllabus page (the Upskill courses):
                     no slot, but a title, semester and credits

Only pandas (to read the CSV files) and difflib (built into Python, already used in
hybrid_router.py, to correct small spelling mistakes) are used here.
"""

import difflib

import pandas as pd

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
NUMBER_WORDS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]

# The elective groups in the order they appear in the scheme.
# A group that is missing from this list is not shown (a warning is printed at startup).
SLOT_ORDER = [
    "Professional Elective-1",
    "Professional Elective-2",
    "Professional Elective-3",
    "Professional Elective-4",
    "Open Elective-1",
    "Professional Elective-5",
    "Professional Elective-5 Lab",
    "Open Elective-2",
    "Professional Elective-6",
    "Open Elective-3",
]

# Words that mean the student is filtering subjects, not asking for a whole semester
# ("semester 3 subjects with MORE THAN 2 credits"). Those go to the normal router.
FILTER_WORDS = ["more", "less", "greater", "fewer", "least", "most", "above", "below",
                "exactly", "over", "under", "than"]
SUBJECT_WORDS = ["syllabus", "subject", "subjects", "course", "courses", "curriculum",
                 "scheme", "paper", "papers", "elective", "electives"]

# A question with an ELECTIVE word is answered with the electives only ("is there any
# elective in sem 7", "show the electives of sem 6"), unless it also asks for the
# compulsory subjects ("syllabus", "subjects and electives", "including electives", ...).
ELECTIVE_WORDS = ["elective", "electives", "optional", "optionals"]
WITH_COMPULSORY_WORDS = ["syllabus", "including", "compulsory", "core", "mandatory", "everything",
                         "entire", "whole", "along", "also", "plus"]
NOUN_WORDS = ["subject", "subjects", "course", "courses", "paper", "papers"]

# Used to write titles in normal case: 'INDIAN CONSTITUTION AND ...' -> 'Indian Constitution and ...'
SMALL_WORDS = ["And", "Of", "To", "The", "For", "In", "With", "Using", "On", "A", "An"]
CAPITAL_WORDS = ["Ai", "Xai", "(Xai)", "Uav", "Ii", "Iii", "Iv"]

PUNCTUATION = "?.,!:;"

# Small spelling mistakes of these words are corrected ('semster' -> 'semester').
SPELLING_WORDS = ["semester", "semesters", "elective", "electives", "credit", "credits",
                  "syllabus", "subject", "subjects", "course", "courses", "optional"]
SEMESTER_WORDS = ["sem", "sems", "semester", "semesters"]
YEAR_WORDS = ["year", "years"]


# ============================================================
# LOADING THE DATA
# ============================================================

def load_scheme(subjects_path="subjects.csv", electives_path="electives.csv"):
    """
    Return a list of courses. Each course is a dictionary with the keys
    code, title, semester, credits and slot.

    slot is empty for a compulsory course, and is the elective group
    ('Open Elective-2', ...) for an elective option.
    """
    courses = pd.read_csv(subjects_path).to_dict("records")

    slots = {}  # course code -> its elective group
    for row in pd.read_csv(electives_path).to_dict("records"):
        if pd.notna(row["slot"]):
            slots[row["code"]] = row["slot"]
        else:
            # No slot: a scheme item that has no syllabus page (Upskill).
            # It is only needed for the credit total.
            courses.append({"code": row["code"], "title": row["title"],
                            "semester": row["semester"], "credits": row["credits"]})

    for course in courses:
        course["slot"] = slots.get(course["code"], "")

    check_scheme(courses, slots)
    return courses


def check_scheme(courses, slots):
    """Print a warning for anything in the data that looks wrong."""
    known_codes = []
    for course in courses:
        known_codes.append(course["code"])

    for code in slots:
        if code not in known_codes:
            print(f"[WARNING] electives.csv lists {code}, which is not in subjects.csv")

    for slot in slots.values():
        if slot not in SLOT_ORDER:
            print(f"[WARNING] elective group '{slot}' is missing from SLOT_ORDER in semester_summary.py")

    # All options of one group should have the same credits.
    for slot in SLOT_ORDER:
        credits_by_code = {}
        for course in courses:
            if course["slot"] == slot:
                credits_by_code[course["code"]] = course["credits"]
        if len(set(credits_by_code.values())) > 1:
            print(f"[WARNING] the options of '{slot}' have different credits: {credits_by_code}")


# ============================================================
# THE NUMBERS FOR ONE SEMESTER
# ============================================================

def get_semester(courses, sem):
    """
    Split one semester into its compulsory courses and its elective groups.

    Returns (compulsory, groups):
        compulsory - list of courses, theory first and labs after
        groups     - list of (group name, list of options, credits of ONE option)
    """
    theory = []
    labs = []
    options_by_slot = {}

    for course in courses:
        if course["semester"] != sem:
            continue
        if course["slot"] != "":
            if course["slot"] not in options_by_slot:
                options_by_slot[course["slot"]] = []
            options_by_slot[course["slot"]].append(course)
        elif course["title"].upper().endswith(" LAB"):
            labs.append(course)
        else:
            theory.append(course)

    groups = []
    for slot in SLOT_ORDER:
        if slot in options_by_slot:
            options = options_by_slot[slot]
            credits = 0
            for option in options:
                if option["credits"] > credits:
                    credits = option["credits"]
            groups.append((slot, options, credits))

    return theory + labs, groups


def add_credits(compulsory, groups):
    """Return (credits of the compulsory courses, credits of the elective groups).
    Each group is counted once, because a student takes only one subject from it."""
    compulsory_credits = 0
    for course in compulsory:
        compulsory_credits += course["credits"]

    elective_credits = 0
    for slot, options, credits in groups:
        elective_credits += credits

    return compulsory_credits, elective_credits


# ============================================================
# UNDERSTANDING THE QUESTION
# ============================================================

def clean(word):
    """Remove punctuation around a word."""
    return word.strip(PUNCTUATION)


def read_number(word):
    """Turn '7', '7th', 'vii' or 'seventh' into 7. Anything else (or a number outside 1-8) gives 0."""
    word = clean(word)
    if word[-2:] in ["st", "nd", "rd", "th"] and word[:-2].isdigit():
        word = word[:-2]

    number = 0
    if word.isdigit():
        number = int(word)
    elif word.upper() in ROMAN:
        number = ROMAN.index(word.upper()) + 1
    elif word in NUMBER_WORDS:
        number = NUMBER_WORDS.index(word) + 1

    if number < 1 or number > 8:
        return 0
    return number


def fix_spelling(word):
    """'semster' -> 'semester'. A word that is not a small spelling mistake of a known word stays as it is."""
    if len(word) < 5 or word in SPELLING_WORDS:
        return word
    close = difflib.get_close_matches(word, SPELLING_WORDS, n=1, cutoff=0.85)
    if len(close) > 0:
        return close[0]
    return word


def numbers_before(words, i, ordinals_only):
    """
    Read the numbers just in front of the word at position i, like '7th' in '7th sem'
    or '6th and 7th' in '6th and 7th sem'. With ordinals_only a plain digit ('3 sem')
    is not read, so that '7th sem 3 credits' does not take the 3 as a semester.

    Returns (numbers, positions of the words that were read).
    """
    numbers = []
    positions = []
    j = i - 1
    while j >= 0 and read_number(words[j]) > 0:
        if ordinals_only and len(numbers) == 0 and words[j].isdigit():
            break
        numbers.append(read_number(words[j]))
        positions.append(j)
        if j >= 2 and words[j - 1] == "and" and read_number(words[j - 2]) > 0:
            positions.append(j - 1)
            j = j - 2
        else:
            break
    return numbers, positions


def numbers_after(words, i):
    """
    Read the numbers just after the word at position i, like '6' in 'sem 6', '6 and 7'
    in 'sem 6 and 7' and '5 to 7' in 'sem 5 to 7'. A number in front of 'credits' after
    an 'and' is not read ('sem 6 and 3 credits').

    Returns (numbers, positions of the words that were read).
    """
    numbers = []
    positions = []
    j = i + 1
    while j < len(words) and read_number(words[j]) > 0:
        numbers.append(read_number(words[j]))
        positions.append(j)

        if j + 2 < len(words) and words[j + 1] in ["to", "till", "through"] and read_number(words[j + 2]) > 0:
            for number in range(read_number(words[j]) + 1, read_number(words[j + 2]) + 1):
                numbers.append(number)
            positions.append(j + 1)
            positions.append(j + 2)
            break

        another = j + 2 < len(words) and words[j + 1] == "and" and read_number(words[j + 2]) > 0
        before_credits = j + 3 < len(words) and words[j + 3] in ["credit", "credits"]
        if another and not before_credits:
            positions.append(j + 1)
            j = j + 2
        else:
            break
    return numbers, positions


def numbers_next_to(words, i):
    """Read the numbers next to a 'sem' or 'year' word, on whichever side they are."""
    numbers, positions = numbers_before(words, i, True)        # 7th sem
    if len(numbers) == 0:
        numbers, positions = numbers_after(words, i)            # sem 7
    if len(numbers) == 0:
        numbers, positions = numbers_before(words, i, False)    # 7 sem
    return numbers, positions


def find_semesters(question):
    """
    Find the semesters named in the question.

    Returns (list of Roman numerals, the other words of the question), or None if no
    semester is named. Understands: 7th sem, semester 7, sem-7, sem7, semester VII,
    vii sem, seventh semester; several semesters ('sem 6 and 7', '6th and 7th sem',
    'sem 5 to 7'); and years ('3rd year' is semesters 5 and 6, 'final year' is 7 and 8).
    Small spelling mistakes ('semster', 'electves') are corrected first.
    """
    text = question.lower().replace("-", " ").replace(",", " and ").replace("&", " and ")
    words = []
    for word in text.split():
        words.append(fix_spelling(clean(word)))

    numbers = []   # the semester numbers found
    used = []      # the positions of the words that name a semester
    for i in range(len(words)):
        word = words[i]
        if word in SEMESTER_WORDS:
            found, positions = numbers_next_to(words, i)
            if len(found) > 0:
                numbers = numbers + found
                used = used + positions + [i]
        elif word.startswith("sem") and read_number(word[3:]) > 0:      # sem7
            numbers.append(read_number(word[3:]))
            used.append(i)
        elif word in YEAR_WORDS:
            found, positions = numbers_next_to(words, i)
            if len(found) == 0 and i > 0 and words[i - 1] in ["final", "last"]:
                found = [4]
                positions = [i - 1]
            for year in found:
                if year <= 4:
                    numbers = numbers + [2 * year - 1, 2 * year]   # year 3 = semesters 5 and 6
            if len(found) > 0:
                used = used + positions + [i]

    semesters = []
    for number in range(1, 9):
        if number in numbers:
            semesters.append(ROMAN[number - 1])
    if len(semesters) == 0:
        return None

    other_words = []
    for i in range(len(words)):
        if i not in used:
            other_words.append(words[i])
    return semesters, other_words


def is_filter_question(words):
    """True if the question filters subjects, like 'more than 2 credits' or '1.5 credits'."""
    for i in range(len(words)):
        word = clean(words[i])
        if word in FILTER_WORDS:
            return True
        # a number right before 'credit' or 'credits', like '1.5 credits'
        if i + 1 < len(words) and clean(words[i + 1]) in ["credit", "credits"]:
            if word.replace(".", "", 1).isdigit():
                return True

    return False


# ============================================================
# WRITING THE ANSWER
# ============================================================

def nice_title(title):
    """'INDIAN CONSTITUTION AND FUNDAMENTAL PRINCIPLES' -> 'Indian Constitution and Fundamental Principles'."""
    if title != title.upper():
        return title  # already written in normal case, like 'DevOps Tools'

    words = title.title().split(" ")
    for i in range(len(words)):
        if i > 0 and words[i] in SMALL_WORDS:
            words[i] = words[i].lower()
        if words[i] in CAPITAL_WORDS:
            words[i] = words[i].upper()
    return " ".join(words).replace("-Ii", "-II")


def show(number):
    """3.0 -> '3', 1.5 -> '1.5'."""
    number = round(number, 2)
    if number == int(number):
        return str(int(number))
    return str(number)


def credit_text(number):
    """3 -> '3 credits', 1 -> '1 credit'."""
    if number == 1:
        return "1 credit"
    return show(number) + " credits"


def semester_overview(courses, sem):
    """Every subject of the semester, with each elective group shown as a choice, plus the total."""
    compulsory, groups = get_semester(courses, sem)
    compulsory_credits, elective_credits = add_credits(compulsory, groups)
    total = compulsory_credits + elective_credits

    lines = [f"**Semester {sem}: {show(total)} credits in total**", ""]

    lines.append(f"**Compulsory subjects** ({credit_text(compulsory_credits)})")
    for course in compulsory:
        lines.append(f"- {nice_title(course['title'])} ({course['code']}), {credit_text(course['credits'])}")

    if len(groups) > 0:
        lines.append("")
        lines.append(f"**Elective courses** ({credit_text(elective_credits)}): "
                     "you take one subject from each group below")
        lines.extend(elective_lines(groups))

    lines.append("")
    lines.append("Ask about any subject by name to see its topics.")
    return "\n".join(lines)


def semester_credits(courses, sem):
    """The credit total of the semester with a short breakdown."""
    compulsory, groups = get_semester(courses, sem)
    compulsory_credits, elective_credits = add_credits(compulsory, groups)
    total = compulsory_credits + elective_credits

    lines = [f"**Semester {sem}: {show(total)} credits in total**", ""]
    lines.append(f"- Compulsory subjects: {show(compulsory_credits)}")
    for slot, options, credits in groups:
        lines.append(f"- {slot} (one of {len(options)}): {show(credits)}")

    if len(groups) > 0:
        lines.append("")
        lines.append("Each elective group is counted once, because you take only one subject from it.")
    return "\n".join(lines)


def elective_lines(groups):
    """The elective groups, one after the other: the group name, then its courses with their credits."""
    lines = []
    for slot, options, credits in groups:
        if slot.endswith(" Lab"):
            note = "take the lab of the elective you chose"
        else:
            note = "choose one"
        lines.append("")
        lines.append(f"**{slot}** ({note})")
        for option in options:
            lines.append(f"- {nice_title(option['title'])} ({option['code']}), {credit_text(option['credits'])}")
    return lines


def semester_electives(courses, sem, words):
    """
    Answer a question about the elective courses of a semester, group by group.

    The first line answers what was asked: a yes/no ('is there any elective'), the
    number of electives, the elective credits, or just a heading when the electives
    were only asked to be shown. words are the words of the question.
    """
    asks_if_any = has_any(words, ["any", "there", "does", "do"])

    compulsory, groups = get_semester(courses, sem)
    if len(groups) == 0:
        if asks_if_any:
            return (f"**No, Semester {sem} has no elective courses.** "
                    "All its subjects are compulsory.")
        return (f"**Semester {sem} has no elective courses.** "
                "All its subjects are compulsory.")

    compulsory_credits, elective_credits = add_credits(compulsory, groups)

    options = 0
    for slot, group_options, credits in groups:
        options += len(group_options)
    if len(groups) == 1:
        group_text = "1 group"
        subject_text = "1 elective subject"
    else:
        group_text = f"{len(groups)} groups"
        subject_text = f"{len(groups)} elective subjects"

    asks_for_credits = has_any(words, ["credit", "credits"])
    if asks_for_credits and (asks_for_a_number(words) or has_any(words, ["total", "sum", "overall"])):
        first_line = (f"**Semester {sem} has {show(elective_credits)} elective credits.** "
                      f"You take one subject from each of its {group_text}.")
    elif asks_for_a_number(words):
        first_line = (f"**Semester {sem} has {options} elective courses, in {group_text}.** "
                      f"You take one subject from each group, so {subject_text} in total.")
    elif asks_if_any:
        first_line = (f"**Yes, Semester {sem} has elective courses.** "
                      "You take one subject from each group below.")
    else:
        first_line = (f"**Semester {sem}: elective courses.** "
                      "You take one subject from each group below.")

    lines = [first_line]
    lines.extend(elective_lines(groups))
    lines.append("")
    lines.append(f"Elective credits in total: {show(elective_credits)} (one subject from each group).")
    return "\n".join(lines)


def has_any(words, wanted):
    """True if any of the words is in the wanted list."""
    for word in words:
        if word in wanted:
            return True
    return False


def asks_for_a_number(words):
    """True for 'how many ...', 'number of ...' or 'count ...'."""
    text = " ".join(words)
    return "how many" in text or "number of" in text or "count" in words


def is_count_question(words):
    """True for 'how many subjects ...', 'number of subjects ...' or 'count the subjects ...'."""
    names_subjects = "subjects" in words or "courses" in words or "papers" in words
    return asks_for_a_number(words) and names_subjects


def wants_more_than_electives(words):
    """True if the question also asks for the compulsory subjects, like 'subjects and electives'."""
    if has_any(words, ["only", "just"]):
        return False
    if has_any(words, WITH_COMPULSORY_WORDS):
        return True

    # 'elective courses' means the electives only, so take those two words out first.
    # A 'subjects' or 'courses' left over, joined with 'and' or 'with', asks for all of them.
    others = []
    i = 0
    while i < len(words):
        if words[i] in ELECTIVE_WORDS and i + 1 < len(words) and words[i + 1] in NOUN_WORDS:
            i += 2
        else:
            others.append(words[i])
            i += 1
    return has_any(others, NOUN_WORDS) and has_any(others, ["and", "with"])


def read_credit_filter(words):
    """
    Find a credit condition such as 'more than 2', 'at least 3' or '1.5 credits'.

    Returns (operator, number), for example ('>', 2.0), or None if the question has no number.
    """
    for i in range(len(words)):
        if not words[i].replace(".", "", 1).isdigit():
            continue
        number = float(words[i])
        before = words[max(0, i - 2):i]   # up to two words in front, like ['more', 'than']
        after = words[i + 1:i + 3]        # up to two words behind, like ['or', 'more']

        if before[-2:] == ["at", "least"] or after[:2] == ["or", "more"]:
            return ">=", number
        if before[-2:] == ["at", "most"] or after[:2] == ["or", "less"] or after[:2] == ["or", "fewer"]:
            return "<=", number
        if has_any(before, ["more", "greater", "above", "over"]):
            return ">", number
        if has_any(before, ["less", "fewer", "below", "under"]):
            return "<", number
        return "=", number
    return None


def credits_match(credits, operator, number):
    """True if the credits fit the condition, like credits > 2."""
    if operator == ">":
        return credits > number
    if operator == ">=":
        return credits >= number
    if operator == "<":
        return credits < number
    if operator == "<=":
        return credits <= number
    return credits == number


def condition_text(operator, number):
    """('>', 2.0) -> 'more than 2 credits'."""
    if operator == ">":
        return f"more than {show(number)} credits"
    if operator == ">=":
        return f"at least {show(number)} credits"
    if operator == "<":
        return f"less than {show(number)} credits"
    if operator == "<=":
        return f"at most {show(number)} credits"
    return f"{show(number)} credits"


def semester_filtered(courses, sem, words, only_electives):
    """
    The subjects of a semester that fit a credit condition such as 'more than 2 credits',
    with the elective courses shown group by group.

    Returns None when the normal router should answer instead: the semester has no
    electives (the router's table answer is already right) or no credit number was found.
    """
    compulsory, groups = get_semester(courses, sem)
    condition = read_credit_filter(words)
    if len(groups) == 0 or condition is None:
        return None
    operator, number = condition

    matching_compulsory = []
    if not only_electives:
        for course in compulsory:
            if credits_match(course["credits"], operator, number):
                matching_compulsory.append(course)

    matching_groups = []
    elective_count = 0
    for slot, options, credits in groups:
        matching_options = []
        for option in options:
            if credits_match(option["credits"], operator, number):
                matching_options.append(option)
        if len(matching_options) > 0:
            matching_groups.append((slot, matching_options, credits))
            elective_count += len(matching_options)

    if only_electives:
        what = "elective courses"
    else:
        what = "subjects"
    wanted = condition_text(operator, number)

    if len(matching_compulsory) == 0 and len(matching_groups) == 0:
        return f"**No {what} in Semester {sem} have {wanted}.**"

    lines = [f"**Semester {sem}: {what} with {wanted}**", ""]
    if only_electives:
        lines.append(f"Elective courses: {elective_count}")
    else:
        lines.append(f"Compulsory subjects: {len(matching_compulsory)}. Elective courses: {elective_count}.")

    if len(matching_compulsory) > 0:
        lines.append("")
        lines.append("**Compulsory subjects**")
        for course in matching_compulsory:
            lines.append(f"- {nice_title(course['title'])} ({course['code']}), {credit_text(course['credits'])}")

    if len(matching_groups) > 0:
        lines.append("")
        lines.append("**Elective courses** (you take one subject from each group)")
        lines.extend(elective_lines(matching_groups))
    return "\n".join(lines)


def semester_count(courses, sem):
    """How many subjects a student takes in the semester (each elective group counts as one)."""
    compulsory, groups = get_semester(courses, sem)
    total = len(compulsory) + len(groups)

    options = 0
    for slot, group_options, credits in groups:
        options += len(group_options)

    lines = [f"**Semester {sem}: {total} subjects**", ""]
    lines.append(f"- Compulsory subjects: {len(compulsory)}")
    if len(groups) > 0:
        lines.append(f"- Electives: {len(groups)} (one subject from each of {len(groups)} groups, "
                     f"chosen from {options} options)")
        lines.append("")
        lines.append("Each elective group counts as one subject, because you take only one from it.")
    return "\n".join(lines)


def semester_reply(question, courses, mentions_subject):
    """
    Answer a whole-semester question, or return None if the question is something else.

    Handles questions such as 'syllabus for 7th sem', 'total credits for sem 7',
    'how many subjects are there in semester 6', 'is there any elective in sem 7'
    and 'electives of sem 6 with 3 credits'. A question that names several semesters
    or a year ('credits of sem 6 and 7', '3rd year') gets one answer per semester.
    A question that names a subject ('credits of DBMS in sem 4') returns None, and so
    does a credit filter on a semester without electives ('semester 3 subjects with
    more than 2 credits'): the normal router answers those. mentions_subject(question)
    says whether the question names a subject (the router passes its own title and
    short-form matching).
    """
    found = find_semesters(question)
    if found is None:
        return None
    semesters, words = found

    if mentions_subject(question):
        return None

    asks_for_electives = has_any(words, ELECTIVE_WORDS) and not wants_more_than_electives(words)

    answers = []
    kinds = []
    for sem in semesters:
        answer, kind = answer_semester(courses, sem, words, asks_for_electives)
        if answer is None:
            return None  # one semester cannot be answered here, so the normal router takes the whole question
        answers.append(answer)
        kinds.append(kind)

    text = "\n\n---\n\n".join(answers)
    if len(semesters) > 1 and kinds.count("credits") == len(kinds):
        text += "\n\n---\n\n" + together_line(courses, semesters)
    return text


def answer_semester(courses, sem, words, asks_for_electives):
    """Answer the question for ONE semester. Returns (answer, kind), or (None, "") if it cannot be answered here."""
    if is_filter_question(words):
        return semester_filtered(courses, sem, words, asks_for_electives), "filter"
    if asks_for_electives:
        return semester_electives(courses, sem, words), "electives"
    if is_count_question(words):
        return semester_count(courses, sem), "count"
    if has_any(words, SUBJECT_WORDS):
        return semester_overview(courses, sem), "overview"
    if has_any(words, ["credit", "credits"]):
        return semester_credits(courses, sem), "credits"
    return None, ""


def together_line(courses, semesters):
    """'Semester V + Semester VI: 46.5 credits together'."""
    total = 0
    names = []
    for sem in semesters:
        compulsory, groups = get_semester(courses, sem)
        compulsory_credits, elective_credits = add_credits(compulsory, groups)
        total += compulsory_credits + elective_credits
        names.append(f"Semester {sem}")
    return f"**{' + '.join(names)}: {show(total)} credits together**"
