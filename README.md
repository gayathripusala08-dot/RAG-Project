# CBIT AI&DS Syllabus Assistant

A chatbot where you can ask questions about our college syllabus (CBIT, AI & Data Science) and get answers in plain English.

Live demo: https://rag-project-juewjwswwdwtlxvx77cxgr.streamlit.app

(The app sleeps if nobody opens it for a while. If you see a "wake up" button, click it and wait a minute.)

## Why I made this

Our syllabus is a 230 page PDF. Finding what a subject covers, or how many credits it has, means scrolling through pages. I wanted to just type a question and get the answer. This is my first project of this kind, so I learned a lot of things while building it (RAG, embeddings, text-to-SQL).

## What it can do

- Tell you what a subject covers ("What topics are covered in Data Structures?")
- Answer questions about credits and semester ("Which semester 3 subjects have more than 2 credits?")
- Answer both in one question ("What does Cloud Computing cover and in which semester is it taught?")
- Understand short names like DAA, DBMS, OS, EDA, ICFP, DLCA
- Reply politely if you say "hi" or ask something unrelated

## How it works

The data is in two forms, so the app first decides where to look. This part is called the router.

1. **Documents**: the syllabus text of each subject is turned into embeddings and stored in a FAISS index. For a question about topics, the app finds the closest subjects and the LLM writes the answer from them.
2. **Table**: subject code, title, semester and credits are in a small SQLite table. For a question about numbers, the LLM writes a SQL query, the app runs it and shows the result.
3. **Both**: if the question needs both, it is split into two smaller questions, each goes to its own side, and the answers are shown together.

Before all this, short forms like DAA are expanded into full subject names, because the search works much better with the full title.

## Tech used

- Python
- sentence-transformers (all-MiniLM-L6-v2) for embeddings
- FAISS for searching
- Groq API (openai/gpt-oss-20b) as the LLM
- SQLite and pandas for the table
- Streamlit for the website

## Files

- `app.py` : the Streamlit website
- `hybrid_router.py` : the main logic (router, search, SQL, short forms)
- `server.py` : a FastAPI version of the backend (I did not use this one for the demo)
- `run_eval.py` : tests the system on a list of questions
- `eval_questions.csv`, `eval_fresh_questions.csv` : the test questions
- `subjects.csv` : the subject table (code, title, semester, credits)
- `syllabus_content.csv` : the syllabus text for each subject
- `extract.py`, `split_subjects.py`, `extract_syllabus_content.py` : scripts I used to pull the data out of the PDF
- `Syllabus.pdf` : the original syllabus

## Run it on your computer

1. Clone the repo and install the packages:
   ```
   pip install -r requirements.txt
   ```
2. Get a free API key from Groq and set it as an environment variable called `projectapi`.
   On Windows (PowerShell):
   ```
   setx projectapi "your_key_here"
   ```
   Then open a new terminal.
3. Start the app:
   ```
   python -m streamlit run app.py
   ```

The first run takes a little time because it downloads the embedding model.

## Testing

`run_eval.py` runs a set of questions and checks three things: did the router pick the right source, did the search find the right subject, and was the final answer correct. I used it to find mistakes and fix them. For example, it showed me that questions with two subjects were failing, which I then fixed.

## Problems I faced

- Short forms like DAA did not work at first, so the search missed the subject. I added a step that expands them before searching.
- When one question had two subjects, the top search results were mixed up. I fixed it by matching the full subject title first and using the search only for the remaining spots.
- Some subjects were missing from my data because of typos in the PDF itself (for example one subject code was written wrongly). I had to correct them by hand.
- The Groq free plan has a limit on how many requests you can send per minute, so too many questions in a row will show a limit message.

## Limitations

- Answers depend on the LLM, so it can sometimes be wrong. Please check anything important in the official syllabus.
- It only knows the AI&DS syllabus in the PDF.
- Subjects that share the same short form (like SE or ES) need the full name.

## What I want to add later

- Show all the subjects used when comparing more than one
- Show the table results as a proper table
- More test questions

Made by Gayathri
