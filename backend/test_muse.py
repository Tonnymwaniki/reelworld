import base64, os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(
    base_url="https://inference.baseten.co/v1",
    api_key=os.environ["BASETEN_API_KEY"],
)

path = r"C:\Users\hp\Projects\reelworld\data\photos\world\market\market_001.jpg"
with open(path, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

response = client.chat.completions.create(
    model="meta-models/muse-spark-open-1026",
    messages=[{
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe what is visible in this photo: the main objects, what is happening, and any visible text."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }],
)
print(response.choices[0].message.content)