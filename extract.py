import pdfplumber

with pdfplumber.open("Syllabus.pdf") as pdf:
    all_text = ""
    for page in pdf.pages:
        text = page.extract_text()
        if text:
            all_text += text + "\n"

with open("raw_syllabus.txt", "w", encoding="utf-8") as f:
    f.write(all_text)

print("Done! Extracted", len(pdf.pages), "pages.")