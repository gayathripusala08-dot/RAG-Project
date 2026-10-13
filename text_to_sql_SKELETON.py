import pandas as pd
import sqlite3
from groq import Groq
import os

# Load subjects.csv into a temporary in-memory SQLite database so we
# can run real SQL queries against it
df = pd.read_csv('subjects.csv')
conn = sqlite3.connect(':memory:')
df.to_sql('subjects', conn, index=False, if_exists='replace')

# API key is read from an environment variable, never hardcoded
client = Groq(api_key=os.environ["projectapi"])

question = "Which semester 3 subjects have more than 2 credits?"

# Prompt includes the table schema and the semester format (Roman
# numerals), since the LLM has no memory of this data between calls
sql_prompt = (
    f"The table 'subjects' has columns: code, title, semester, credits. "
    f"semester is stored as Roman numerals (I, II, III...), not numbers. "
    f"Write ONLY a SQL query (no explanation) to answer: {question}"
)

response = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": sql_prompt}]
)
generated_sql = response.choices[0].message.content.strip()
print("Generated SQL:")
print(generated_sql)

# Run the generated SQL against our database
try:
    result = pd.read_sql_query(generated_sql, conn)
    print("\nResults:")
    print(result)
except Exception as e:
    print("\nSQL execution failed:", e)