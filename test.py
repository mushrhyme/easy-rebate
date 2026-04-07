import os
from dotenv import find_dotenv, load_dotenv
from openai import OpenAI

def main():
    dotenv_path = find_dotenv(usecwd=True)
    load_dotenv(dotenv_path=dotenv_path, override=True)
    api_key = os.getenv("OPENAI_API_KEY", "").strip()

    client = OpenAI(api_key=api_key)
 
    resp = client.chat.completions.create(
        model="gpt-5.2-2025-12-11",
        messages=[{"role": "user", "content": "pong이라고만 답해줘."}]
    )
    print(resp.choices[0].message.content.strip())
 

if __name__ == "__main__":
    main()
