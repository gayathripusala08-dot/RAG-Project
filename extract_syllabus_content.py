import re
import csv
import pdfplumber

PDF_PATH = "Syllabus.pdf"  # make sure this file is in the same folder as this script

# Every page of the PDF has a repeating header (the department name at the top)
# and footer (the college name at the bottom). When a subject runs onto the next
# page, these lines would land in the middle of its text, so we remove them.
HEADER_FOOTER_LINES = [
    re.compile(r"^ARTIFICIAL INTELLIGENCE\s*(AND|&)\s*DATA SCIENCE$", re.IGNORECASE),
    re.compile(r"^C\s?haitanya Bharathi Institute of Technology(\s*\(A\))?$", re.IGNORECASE),
]


# A few subject pages put the code and the title on ONE line, like
# "22ADC73N PROJECT PART-I". The rest of the script looks for a code on its own
# line, so these pages would be missed and their text would be added to the
# subject before them. We split such a first line into two lines.
CODE_AND_TITLE_FIRST_LINE = re.compile(r"^(\d{2}[A-Z]{2,5}\d{1,3}N?)\s+(\S.*)$")

# The PDF has a typo: the Robotic Process Automation page says 22CSE723, but the
# semester table (and everywhere else) says 22CSE23.
CODE_FIXES = {"22CSE723": "22CSE23"}


def remove_header_footer(page_text):
    """Drop the lines that are exactly a page header or footer, and split a joined code + title line."""
    kept = [
        line for line in page_text.split("\n")
        if not any(pattern.match(line.strip()) for pattern in HEADER_FOOTER_LINES)
    ]
    if kept:
        joined = CODE_AND_TITLE_FIRST_LINE.match(kept[0].strip())
        if joined:
            kept[0:1] = [joined.group(1), joined.group(2)]
    return "\n".join(kept)


# Where the useful syllabus text ends: reading lists, web links and the outcome
# matrix are not topics, so the content is cut at the first of these.
END_MARKERS = [
    'textbooks:', 'textbook:', 'text books:', 'text book:', 'suggested reading',
    'web resources', 'reference books', 'references:',
    'co-po articulation', 'course articulation',
]

# The outcome matrix is a block of PO1..PSO3 headings followed by rows of numbers.
MATRIX_PATTERN = re.compile(r"PO1\s+PO2\s+PO3.*?PSO3(?:\s+(?:CO\d+|[\d\-–]+))*", re.DOTALL)


# STEP 1: Pull all the text out of the PDF, page by page
print("Reading PDF (this can take a minute for a 230-page file)...")
full_text = ""
with pdfplumber.open(PDF_PATH) as pdf:
    for page in pdf.pages:
        page_text = page.extract_text()
        if page_text:
            full_text += remove_header_footer(page_text) + "\n"
print(f"Done reading. Total characters extracted: {len(full_text)}")

# STEP 2: Find every subject code (like 22ITC20N, 22MTC01) sitting alone on its own line
code_pattern = re.compile(r'^\s*(\d{2}[A-Z]{2,5}\d{1,3}N?)\s*$', re.MULTILINE)
matches = list(code_pattern.finditer(full_text))
print(f"Found {len(matches)} subject code occurrences")

# STEP 3: For each code, grab the text between it and the NEXT code -
# that chunk is "everything about this one subject"
results = {}
for i, m in enumerate(matches):
    code = m.group(1)
    start = m.end()
    end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
    block = full_text[start:end]  # the text belonging to just this one subject
    block_lower = block.lower()

    # Skip this match if it's not actually a detail page
    # (the code also appears earlier in a short summary table - we skip that one)
    if 'course objectives' not in block_lower and 'instruction' not in block_lower:
        continue

    content = ""

    # STEP 4a: Theory subjects have "UNIT I", "UNIT-I" etc. - grab from there onward
    unit_matches = list(re.finditer(r'UNIT[\s\-]*[IVX]+\s*:?', block))
    if unit_matches:
        unit_start = unit_matches[0].start()
        unit_end = len(block)
        for marker in END_MARKERS:
            idx = block_lower.find(marker, unit_start)
            if idx != -1:
                unit_end = min(unit_end, idx)
        content = block[unit_start:unit_end]

    # STEP 4b: Lab subjects use different headers depending on the page
    else:
        lab_headers = ['lab experiments', 'list of programs', 'list of experiments', 'experiments:']
        lab_idx = -1
        for h in lab_headers:
            idx = block_lower.find(h)
            if idx != -1:
                lab_idx = idx
                break
        if lab_idx != -1:
            lab_end = len(block)
            for marker in END_MARKERS:
                idx = block_lower.find(marker, lab_idx)
                if idx != -1:
                    lab_end = min(lab_end, idx)
            content = block[lab_idx:lab_end]

        # STEP 4c: A few subjects (Internship, Seminar, value-add courses) have
        # neither units nor a lab list - fall back to Objectives + Outcomes text
        else:
            obj_idx = block_lower.find('course objectives')
            if obj_idx != -1:
                obj_end = len(block)
                for marker in END_MARKERS:
                    idx = block_lower.find(marker, obj_idx)
                    if idx != -1:
                        obj_end = min(obj_end, idx)
                content = block[obj_idx:obj_end]

        # STEP 4d: Last resort (for example Technical Seminar has no objectives):
        # use the description that follows the "Credits" line.
        if not content.strip():
            credits_line = re.search(r"credits\s+\S+", block_lower)
            if credits_line:
                text_end = len(block)
                for marker in END_MARKERS:
                    idx = block_lower.find(marker, credits_line.end())
                    if idx != -1:
                        text_end = min(text_end, idx)
                content = block[credits_line.end():text_end]

    # STEP 5: Clean up - remove page footer text and collapse extra blank space
    content = re.sub(r'Chaitanya Bharathi Institute of Technology.*', '', content)

    # The last subject before a semester's scheme table would otherwise pick up
    # that table's text. Cut it off where the table page starts.
    content = re.split(r"\(AUTONOMOUS\)\s*DEP[A-Z]*MENT OF", content, maxsplit=1)[0]
    content = re.sub(r'\s+', ' ', content).strip()
    content = MATRIX_PATTERN.sub('', content)
    content = re.sub(r'\s+', ' ', content).strip()
    code = CODE_FIXES.get(code, code)

    # STEP 6: Keep this subject only if we actually got real content,
    # and keep the longer version if the same code showed up more than once
    if content and len(content) > 30:
        if code not in results or len(content) > len(results[code]):
            results[code] = content

print(f"Extracted content for {len(results)} subjects")

# STEP 7: Save everything to a CSV file
with open('syllabus_content.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['code', 'content'])
    for code, content in results.items():
        writer.writerow([code, content])

print("Saved to syllabus_content.csv")