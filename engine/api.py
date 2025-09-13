from flask import Flask, Blueprint, jsonify, request, render_template
from flasgger import Swagger, swag_from
from engine.tasks import nltk_smart_chunk, langchain_smart_chunk, get_rabbit_connection
import pika
import json
import os
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

api = Blueprint('api', __name__)

def log_event():
    logger.info(f"Request at {datetime.now().isoformat()} from {request.remote_addr}")

@api.route('/', methods=['GET'])
def buy_me_a_coffee():
    ascii_art = '''
          "author":"Piotr Romanowski"
          "version": "2.3"
    '''
    return render_template('index.html', ascii_art=ascii_art)

@api.route('/ver', methods=['GET'])
@swag_from('static/swagger.json', endpoint='api.version')
def version():
    log_event()
    return jsonify({
        "version": "2.3",
        "author": "Piotr Romanowski",
        "compiled": "13-09-2025 11:39",
        "served_by": os.uname()[2],
        "container": os.path.exists('/.dockerenv')
    })

@api.route('/health', methods=['GET'])
@swag_from('static/swagger.json', endpoint='api.health')
def health():
    log_event()
    return jsonify({"status": "ok"})

@api.route('/docs', methods=['GET'])
def get_docs():
    return render_template('swaggerui.html')

@api.route('/split/<strategy>', methods=['POST'])
@swag_from('static/swagger.json', endpoint='api.split_text')
def split_text(strategy):
    if strategy not in ['nltk', 'langchain']:
        return jsonify({"error": "Invalid strategy: use 'nltk' or 'langchain'"}), 400

    data = get_input()
    if 'error' in data:
        return jsonify(data), 400

    queue = data.get('queue')
    text = data['text']
    params = data['params']
    chunk_func = nltk_smart_chunk if strategy == 'nltk' else langchain_smart_chunk

    try:
        chunks = chunk_func(text, **params)
        if queue:
            connection = get_rabbit_connection()
            channel = connection.channel()
            channel.basic_publish(
                exchange='',
                routing_key='splitter_chunks',
                body=json.dumps(chunks, ensure_ascii=False),
                properties=pika.BasicProperties(delivery_mode=2)
            )
            connection.close()
            return jsonify({"status": "queued", "num_chunks": len(chunks)})
        return jsonify(chunks)
    except Exception as e:
        logger.error(f"Error processing split: {str(e)}")
        return jsonify({"error": str(e)}), 500

def get_input():
    params = {
        'chunk_size': int(request.form.get('chunk_size', request.json.get('chunk_size', 1024))) if request.form.get('chunk_size') or (request.is_json and request.json.get('chunk_size')) else 1024,
        'chunk_overlap': int(request.form.get('chunk_overlap', request.json.get('chunk_overlap', 128))) if request.form.get('chunk_overlap') or (request.is_json and request.json.get('chunk_overlap')) else 128
    }
    if request.form.get('min_chunk_size') or (request.is_json and request.json.get('min_chunk_size')):
        params['min_chunk_size'] = int(request.form.get('min_chunk_size', request.json.get('min_chunk_size', 100)))

    queue = request.form.get('queue') or (request.json.get('queue') if request.is_json else None)
    if queue:
        connection = get_rabbit_connection()
        channel = connection.channel()
        method, _, body = channel.basic_get(queue=queue, auto_ack=True)
        connection.close()
        if not body:
            return {"error": "No message in queue"}
        try:
            text = json.loads(body.decode('utf-8')).get('text', '')
        except json.JSONDecodeError:
            return {"error": "Invalid queue message format"}
    elif 'file' in request.files:
        file = request.files['file']
        if file.filename == '':
            return {"error": "No file selected"}
        text = file.read().decode('utf-8')
    elif request.is_json:
        try:
            text = request.json.get('text', '')
        except json.JSONDecodeError:
            return {"error": "Invalid JSON format"}
    else:
        return {"error": "Provide 'text' in JSON, 'queue', or upload 'file'"}
    
    if not text.strip():
        return {"error": "Empty input"}
    return {'text': text, 'queue': queue, 'params': params}

def create_app():
    app = Flask(__name__)
    app.register_blueprint(api)
    
    # Configure Flasgger for OpenAPI
    Swagger(app, template_file='static/swagger.json')
    
    # Start RabbitMQ consumer in background
    import threading
    threading.Thread(target=start_queue_consumer, daemon=True).start()
    
    return app

def start_queue_consumer():
    try:
        connection = get_rabbit_connection()
        channel = connection.channel()
        
        def callback(ch, method, properties, body):
            try:
                data = json.loads(body.decode('utf-8'))
                strategy = data.get('strategy', 'nltk')
                text = data.get('text', '')
                params = data.get('params', {'chunk_size': 1024, 'chunk_overlap': 128})
                chunk_func = nltk_smart_chunk if strategy == 'nltk' else langchain_smart_chunk
                chunks = chunk_func(text, **params)
                ch.basic_publish(
                    exchange='',
                    routing_key='splitter_chunks',
                    body=json.dumps(chunks, ensure_ascii=False),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                logger.error(f"Queue consumer error: {str(e)}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        
        channel.basic_consume(queue='splitter', on_message_callback=callback)
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Queue consumer startup error: {str(e)}")
