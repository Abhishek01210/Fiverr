from flask import Flask, request, Response
from flask_cors import CORS
from openai import OpenAI
import json

app = Flask(__name__)
CORS(app)

client = OpenAI(
    api_key="sk-802fe5996aa441199db50ff2c951a261",
    base_url="https://api.deepseek.com"
)

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        messages = data['messages']
        messages_with_system = [{"role": "system", "content": "You are a helpful assistant"}] + messages

        def generate():
            stream = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages_with_system,
                stream=True,
                max_tokens=1024,
                temperature=0.7
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content or ""
                if content:
                    yield f"data: {json.dumps({'content': content})}\n\n"
            yield "data: [DONE]\n\n"

        return Response(generate(), mimetype='text/event-stream')
    except Exception as e:
        print(f'Error: {e}')
        return {"error": "Internal server error"}, 500

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
