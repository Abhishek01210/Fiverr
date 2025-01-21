from flask import Flask, request, jsonify
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from ragflow_sdk import RAGFlow

# Load environment variables
load_dotenv()

RAGFLOW_API_URL = "https://ragflow-ogno0-u30628.vm.elestio.app"
RAGFLOW_API_KEY = "ragflow-Q1NmJhMTcyZDViNTExZWY5ZTY3MDI0Mm"

# Temporary storage for query history
query_history = []

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Initialize RAGFlow object
rag_object = RAGFlow(api_key=RAGFLOW_API_KEY, base_url=RAGFLOW_API_URL)
assistant = rag_object.list_chats(name="icc-cases")[0]

# Store the session as a global variable
global_session = None

def get_or_create_session():
    global global_session
    if global_session is None:
        global_session = assistant.create_session()
    return global_session

@app.route('/')
def home():
    return "Welcome to the RAGFlow chatbot service!"

@app.route('/chat', methods=['POST'])
def chat():
    user_query = request.json.get('query')
    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    # Store query in history
    query_history.append({'query': user_query})

    # Get or create session and process query with RAGFlow
    try:
        session = get_or_create_session()
        cont = ""
        response_content = ""
        for ans in session.ask(user_query, stream=True):
            response_content += ans.content[len(cont):]
            cont = ans.content

        query_history[-1]['response'] = response_content
        return jsonify({'answer': response_content})

    except Exception as e:
        print(f"Ragflow error: {e}")
        return jsonify({'error': 'Unable to process the request at this time'}), 500

@app.route('/history', methods=['GET'])
def get_history():
    return jsonify(query_history)

@app.route('/history/clear', methods=['POST'])
def clear_history():
    global global_session
    query_history.clear()
    # Optionally reset the session when clearing history
    global_session = None
    return jsonify({'message': 'Query history cleared'}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
