from flask import Flask, request, jsonify, Response
import requests
from dotenv import load_dotenv
from flask_cors import CORS
from datetime import datetime, timedelta
import json
import re  # Add at the top with other imports
import boto3
from botocore.exceptions import ClientError
import os
import logging
import threading
from typing import List, Dict, Any
from sklearn.feature_extraction.text import TfidfVectorizer
import nltk
from nltk.stem import WordNetLemmatizer
from nltk.corpus import wordnet
from openai import OpenAI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

client = OpenAI()
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY').strip('"')

# Separate storage for query history and chat titles for each section
query_history = {
    'main': [],
    'for_against': [],
    'bare_acts': []
}

chat_titles = {
    'main': {},
    'for_against': {},
    'bare_acts': {}
}

# Load AWS credentials from .env
# Load AWS credentials from .env
AWS_ACCESS_KEY = os.getenv('AWS_ACCESS_KEY').strip('"')
AWS_SECRET_KEY = os.getenv('AWS_SECRET_KEY').strip('"')
S3_BUCKET = os.getenv('S3_BUCKET').strip('"')
S3_KEY = os.getenv('S3_KEY').strip('"')

# Initialize S3 client
s3 = boto3.client(
    's3',
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY
)

nltk.download('wordnet')
nltk.download('omw-1.4')
lemmatizer = WordNetLemmatizer()

class JudgmentManager:
    _instance = None
    _lock = threading.Lock()
    
    def __init__(self):
        if not hasattr(self, '_judgments'):
            self._judgments = []
            self._loaded = False

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
    
    def load_judgments(self):
        if not self._loaded:
            with self._lock:
                if not self._loaded:
                    try:
                        logger.info("Loading judgments from S3")
                        s3 = boto3.client('s3', aws_access_key_id=AWS_ACCESS_KEY, aws_secret_access_key=AWS_SECRET_KEY)
                        obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY)
                        raw_content = obj['Body'].read().decode('utf-8')
                        raw_content = re.sub(r',(\s*[}\]])', r'\1', raw_content)
                        raw_data = json.loads(raw_content)
                        self._judgments = self.process_judgment_data(raw_data)
                        self._loaded = True
                        logger.info(f"Successfully loaded {len(self._judgments)} judgments")
                    except Exception as e:
                        logger.error(f"Judgment loading failed: {str(e)}")
                        raise

    @staticmethod
    def validate_judgment_data(judgment: Dict[str, Any]) -> bool:
        required_fields = ['JudgmentSummary']
        if not all(field in judgment for field in required_fields):
            return False
        return True

    @staticmethod
    def process_judgment_data(raw_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        processed = []
        for judgment in raw_data:
            try:
                if not JudgmentManager.validate_judgment_data(judgment):
                    continue
                # Append the entire judgment if valid
                processed.append(judgment)
            except Exception as e:
                logger.error(f"Skipping invalid judgment: {str(e)}")
                continue
        return processed

    @property
    def judgments(self):
        if not self._loaded:
            self.load_judgments()
        return self._judgments

def expand_query(query: str) -> List[str]:
    """Expand query with synonyms and lemmas"""
    tokens = query.lower().split()
    expanded = set()
    
    for token in tokens:
        # Add original
        expanded.add(token)
        
        # Add lemma
        lemma = lemmatizer.lemmatize(token)
        expanded.add(lemma)
        
        # Add synonyms
        for syn in wordnet.synsets(token):
            for lemma in syn.lemmas():
                expanded.add(lemma.name().lower())
                
    return list(expanded)

def find_relevant_judgments(query: str) -> List[Dict[str, str]]:
    judgment_manager = JudgmentManager.get_instance()
    expanded_terms = expand_query(query)
    
    # Create TF-IDF matrix using nested fields from the judgment data
    documents = [
        f"{j['JudgmentSummary']['JudgmentName']} {j['JudgmentSummary']['Brief']['Introduction']}" 
        for j in judgment_manager.judgments
    ]
    
    vectorizer = TfidfVectorizer(stop_words='english')
    tfidf_matrix = vectorizer.fit_transform(documents)
    query_vec = vectorizer.transform([' '.join(expanded_terms)])
    
    # Calculate cosine similarities
    similarities = (tfidf_matrix * query_vec.T).toarray().flatten()
    
    # Get top matches
    ranked = sorted(
        zip(similarities, judgment_manager.judgments),
        key=lambda x: x[0],
        reverse=True
    )
    
    return [{
        'name': j['JudgmentSummary']['JudgmentName'],
        'intro': j['JudgmentSummary']['Brief']['Introduction'],
        'score': float(score),
        'matched_terms': list(set(expanded_terms) & set(j['JudgmentSummary']['Brief']['Introduction'].lower().split()))
    } for score, j in ranked[:5] if score > 0]

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

def generate_chat_title(queries):
    try:
        prompt = f"Create a short, descriptive title (max 5 words) for a chat session based on these queries:\n1. {queries[0]}\n2. {queries[1]}"
        
        # Use OpenAI client instead of requests
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that creates concise chat titles."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=20,
            temperature=0.7
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error generating title: {e}")
        return "New Chat"
        
def get_chat_id():
    return datetime.now().strftime("%Y%m%d%H%M%S")

def stream_deepseek_response(user_query, section, chat_id):
    system_messages = {
        'main': "You are a helpful legal assistant, providing clear and accurate information about legal matters.",
        'for_against': "You are a legal analyst specializing in presenting balanced arguments for and against legal positions.",
        'bare_acts': "You are a legal expert focusing on explaining sections of legal acts and statutes in simple terms."
    }

    # Stream using OpenAI client
    stream = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_messages[section]},
            {"role": "user", "content": user_query}
        ],
        max_tokens=8192,
        temperature=0.7,
        stream=True
    )

    full_response = []
    # Stream OpenAI response
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            chunk_content = chunk.choices[0].delta.content
            full_response.append(chunk_content)
            yield f"data: {json.dumps({'content': chunk_content, 'chat_id': chat_id})}\n\n"

    # Add judgments after main response (existing logic remains)
    judgment_text = ""
    if section == 'for_against':
        try:
            judgments = find_relevant_judgments(user_query)
            if judgments:
                judgment_text = "\n\n**Relevant Judgments:**\n"
                for idx, j in enumerate(judgments, 1):
                    judgment_text += f"{idx}. **{j['name']}**\n{j['intro']}\n\n"
                yield f"data: {json.dumps({'content': judgment_text, 'type': 'judgments', 'chat_id': chat_id})}\n\n"
        except Exception as e:
            logger.error(f"Judgment processing failed: {str(e)}")
    
    yield "data: [DONE]\n\n"

    # Store complete response (existing logic remains)
    complete_response = ''.join(full_response)
    query_history[section].append({
        'chat_id': chat_id,
        'query': user_query,
        'response': complete_response,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_query = data.get('query')
    section = data.get('section', 'main')
    chat_id = data.get('chat_id')

    if not user_query:
        return jsonify({'error': 'No query provided'}), 400

    # Generate new chat_id if not provided or invalid
    if not chat_id or chat_id not in chat_titles.get(section, {}):
        chat_id = get_chat_id()
        chat_titles.setdefault(section, {})[chat_id] = {
            'queries': [],
            'title': None,
            'timestamp': datetime.now().isoformat()
        }

    # Store query
    chat_titles[section][chat_id]['queries'].append(user_query)

    # Generate title after second query
    if len(chat_titles[section][chat_id]['queries']) == 2:
        title = generate_chat_title(chat_titles[section][chat_id]['queries'])
        chat_titles[section][chat_id]['title'] = title

    return Response(
        stream_deepseek_response(user_query, section, chat_id),
        mimetype='text/event-stream'
    )

@app.route('/history/<section>', methods=['GET'])
def get_history(section):
    if section not in query_history:
        return jsonify([])

    # Group chats by date
    now = datetime.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    seven_days_ago = today - timedelta(days=7)
    thirty_days_ago = today - timedelta(days=30)

    grouped_history = {
        'today': [],
        'yesterday': [],
        'seven_days': [],
        'thirty_days': []
    }

    # Group chats by their first message
    chat_groups = {}
    for entry in query_history[section]:
        chat_id = entry['chat_id']
        if chat_id not in chat_groups:
            chat_groups[chat_id] = {
                'title': chat_titles[section][chat_id]['title'] or "New Chat",
                'timestamp': datetime.fromisoformat(entry['timestamp']),
                'messages': []
            }
        chat_groups[chat_id]['messages'].append(entry)

    # Sort chats into time periods
    for chat_id, chat in chat_groups.items():
        chat_date = chat['timestamp'].date()
        if chat_date == today:
            grouped_history['today'].append(chat)
        elif chat_date == yesterday:
            grouped_history['yesterday'].append(chat)
        elif chat_date > seven_days_ago:
            grouped_history['seven_days'].append(chat)
        elif chat_date > thirty_days_ago:
            grouped_history['thirty_days'].append(chat)

    return jsonify(grouped_history)

@app.route('/history/<section>/clear', methods=['POST'])
def clear_history(section):
    if section in query_history:
        query_history[section].clear()
        chat_titles[section].clear()
        return jsonify({'message': f'History cleared for {section}'}), 200
    return jsonify({'error': 'Invalid section'}), 400

@app.route('/autocomplete', methods=['GET'])
def autocomplete():
    search_term = request.args.get('term', '').lower()
    section = request.args.get('section', 'main')
    suggestions = []

    if section in query_history:
        words = set()
        # Extract words using regex to ignore punctuation
        word_pattern = re.compile(r'\b\w+\b')
        
        for entry in query_history[section]:
            # Process queries
            query_words = word_pattern.findall(entry['query'].lower())
            # Process responses
            response_words = word_pattern.findall(entry['response'].lower())
            words.update(query_words + response_words)
        
        # Get matching suggestions
        suggestions = [word for word in words if word.startswith(search_term)]
        suggestions = sorted(suggestions)[:5]  # Return top 5 sorted results

    return jsonify(suggestions)

@app.route("/")
def home():
    return "Hello, this is the chatbot!"

@app.route('/debug/judgments')
def debug_judgments():
    judgment_manager = JudgmentManager.get_instance()
    test_query = request.args.get('q', 'medical termination')
    
    return jsonify({
        "total_judgments": len(judgment_manager.judgments),
        "test_query": test_query,
        "expanded_terms": expand_query(test_query),
        "top_matches": find_relevant_judgments(test_query)
    })

def stream_generator():
    yield ""  # Initial empty frame to initialize connection
    while streaming:
        yield data
        time.sleep(0.1)  # Prevent buffer starvation

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
