from flask import Flask, request, jsonify
from tasks import nltk_smart_chunk, langchain_smart_chunk
import pika
import json
import os

app = Flask(__name__)

def get_rabbit_connection():
    credentials = pika.PlainCredentials(
        os.getenv('RABBITMQ_USER', 'peter'),
        os.getenv('RABBITMQ_PASS', 'teachme')
    )
    return pika.BlockingConnection(pika.ConnectionParameters(
        host=os.getenv('RABBITMQ_HOST', '192.168.0.220'),
        port=int(os.getenv('RABBITMQ_PORT', 5672)),
        credentials=credentials
    ))

@app.route('/split/<strategy>', methods=['POST'])
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
            # Queue mode: Publish to splitter_chunks
            connection = get_rabbit_connection()
            channel = connection.channel()
            channel.basic_publish(
                exchange='',
                routing_key='splitter_chunks',
                body=json.dumps(chunks),
                properties=pika.BasicProperties(delivery_mode=2)  # Durable
            )
            connection.close()
            return jsonify({"status": "queued", "num_chunks": len(chunks)})
        # Direct mode: Return chunks
        return jsonify(chunks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_input():
    params = {
        'chunk_size': request.json.get('chunk_size', 1024),
        'chunk_overlap': request.json.get('chunk_overlap', 128)
    }
    if 'min_chunk_size' in request.json:  # For NLTK only
        params['min_chunk_size'] = request.json['min_chunk_size']
    
    queue = request.json.get('queue') if request.is_json else None
    if queue:
        # Fetch from queue
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
        text = request.json.get('text', '')
    else:
        return {"error": "Provide 'text' in JSON, 'queue', or upload 'file'"}
    
    if not text.strip():
        return {"error": "Empty input"}
    return {'text': text, 'queue': queue, 'params': params}

# Start queue consumer in background
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
                    body=json.dumps(chunks),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception:
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # To dlx_exchange
                
        channel.basic_consume(queue='splitter', on_message_callback=callback)
        channel.start_consuming()
    except Exception as e:
        app.logger.error(f"Queue consumer error: {str(e)}")

if __name__ == '__main__':
    import threading
    threading.Thread(target=start_queue_consumer, daemon=True).start()
    app.run()  # Uvicorn handles in CMD
