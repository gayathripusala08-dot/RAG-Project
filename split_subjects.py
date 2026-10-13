import re

# Step 1: read the whole file into one big piece of text
with open("raw_syllabus.txt", "r", encoding="utf-8") as f:
    text = f.read()

# Step 2: find every place a course code sits alone on its own line,
# but only keep it if it's followed shortly by "Instruction" AND
# we haven't crossed into the NEXT subject's page header first
positions = {}

for match in re.finditer(r"^22[A-Z]{2,5}\d{2}[A-Z]?N?$", text, re.MULTILINE):
    code = match.group()
    position = match.start()

    nearby_text = text[position:position + 300]

    instruction_index = nearby_text.find("Instruction")

    # allow for "Chaitanya" OR "C haitanya" (stray space glitch)
    boundary_match = re.search(r"C\s?haitanya", nearby_text)
    boundary_index = boundary_match.start() if boundary_match else -1

    if instruction_index != -1 and (boundary_index == -1 or boundary_index > instruction_index):
        positions[code] = position

# Step 3: sort the positions in order, earliest to latest
sorted_positions = sorted(positions.items(), key=lambda item: item[1])

# Step 4: cut the text into one block per subject, using the sorted positions
subjects = {}  # code -> full text of that subject

for i in range(len(sorted_positions)):
    code, start = sorted_positions[i]

    if i + 1 < len(sorted_positions):
        # there IS a next subject, so stop right before it starts
        next_start = sorted_positions[i + 1][1]
    else:
        # this is the LAST subject, so go to the end of the document
        next_start = len(text)

    subjects[code] = text[start:next_start]

# Step 5: pull out the title (always the line right after the code)
titles = {}  # code -> title

for code, block in subjects.items():
    block_lines = block.split("\n")
    title = block_lines[1].strip()
    titles[code] = title

# Step 6: pull out the credits number (search every line for one starting with "Credits")
credits = {}  # code -> credits value

for code, block in subjects.items():
    block_lines = block.split("\n")
    for line in block_lines:
        clean_line = line.strip()
        if clean_line.startswith("Credits"):
            parts = clean_line.split(" ")
            if len(parts) > 1:
                credits[code] = parts[1]

semester_positions = []  # will hold (position, semester_number) pairs

for match in re.finditer(r"SEMESTER\s*[-–]\s*([IVX]+)", text):
    position = match.start()
    semester_number = match.group(1)  # just the roman numeral part
    semester_positions.append((position, semester_number))

semesters = {}  # code -> semester number

for code, subject_position in positions.items():
    current_semester = None
    for semester_position, semester_number in semester_positions:
        if semester_position < subject_position:
            current_semester = semester_number
        else:
            break
    semesters[code] = current_semester


import csv

# open a new file called subjects.csv, ready to write into it
with open("subjects.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)

    # write the header row first (the column names)
    writer.writerow(["code", "title", "semester", "credits"])

    # now write one row per subject
    for code in subjects:
        title = titles.get(code, "")
        semester = semesters.get(code, "")
        credit = credits.get(code, "")
        writer.writerow([code, title, semester, credit])

print("Saved", len(subjects), "subjects to subjects.csv")

