from scorer import score_job

job = {
    "company": "Test",
    "title": "Senior Data Engineer",
    "location": "Bangalore",
    "url": "https://test.com",
    "description": """
Python
SQL
Snowflake
Databricks
Airflow
Kafka
GCP
AWS
"""
}

result = score_job(job)

print(result)