import json
import urllib.request


OLLAMA_URL = "http://localhost:11434/api/generate"

profile = """
Senior Data Engineer
BigQuery
DBT
GCP
"""

job = """
Senior Data Engineer - Snowflake, DBT, GCP
"""

prompt = f"""
You are scoring job relevance for this candidate.

Resume:
{profile}

Job:
{job}

Return only valid JSON:
{{
  "score": 0-100,
  "reason": "short reason"
}}
"""

payload = {
    "model": "qwen3:8b",
    "prompt": prompt,
    "stream": False,
    "think": False,
    "options": {
        "temperature": 0,
        "num_predict": 120,
    },
}

request = urllib.request.Request(
    OLLAMA_URL,
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)

with urllib.request.urlopen(request, timeout=120) as response:
    result = json.loads(response.read().decode("utf-8"))

print(result["response"])
