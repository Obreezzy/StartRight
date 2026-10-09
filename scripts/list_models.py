from dotenv import load_dotenv
from groq import Groq

load_dotenv()
for model in sorted(Groq().models.list().data, key=lambda m: m.id):
    print(model.id)