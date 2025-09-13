from langchain_text_splitters import RecursiveCharacterTextSplitter
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
import uuid
import pika
import os
import re

def preprocess_text(input_text):
    # Normalize newlines: keep 2-3 \n as paragraph breaks, remove excess
    input_text = re.sub(r'\n{3,}', '\n\n', input_text)
    return input_text.strip()

def nltk_smart_chunk(input_text, chunk_size=1024, chunk_overlap=128, min_chunk_size=100):
    input_text = preprocess_text(input_text)
    paragraphs = input_text.split('\n\n')
    chunk_data = []
    current_chunk = ""
    current_length = 0
    overlap_buffer = ""

    for para in paragraphs:
        sentences = sent_tokenize(para.strip())
        for sentence in sentences:
            sentence += " "
            sentence_len = len(sentence)
            if current_length + sentence_len > chunk_size:
                if current_length >= min_chunk_size:
                    chunk_id = str(uuid.uuid4())
                    full_chunk = overlap_buffer + current_chunk.strip()
                    chunk_data.append({"id": chunk_id, "text": full_chunk})
                    # Ensure overlap ends at word boundary
                    if chunk_overlap > 0:
                        words = word_tokenize(full_chunk)
                        overlap_text = " ".join(words[-int(chunk_overlap / 5):])  # Approx 5 chars/word
                        overlap_buffer = overlap_text[:chunk_overlap] + " "
                    else:
                        overlap_buffer = ""
                    current_chunk = ""
                    current_length = 0
            current_chunk += sentence
            current_length += sentence_len
        if sentences:
            current_chunk += "\n\n"
            current_length += 2
    if current_length >= min_chunk_size:
        chunk_id = str(uuid.uuid4())
        full_chunk = overlap_buffer + current_chunk.strip()
        chunk_data.append({"id": chunk_id, "text": full_chunk})
    return chunk_data

def langchain_smart_chunk(input_text, chunk_size=1024, chunk_overlap=128):
    input_text = preprocess_text(input_text)
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],  # Prioritize paragraph breaks
        add_start_index=True
    )
    chunks = splitter.split_text(input_text)
    return [{"id": str(uuid.uuid4()), "text": chunk} for chunk in chunks]

def get_rabbit_connection():
    credentials = pika.PlainCredentials(
        os.getenv('RABBITMQ_USER', 'username'),
        os.getenv('RABBITMQ_PASS', 'pass')
    )
    return pika.BlockingConnection(pika.ConnectionParameters(
        host=os.getenv('RABBITMQ_HOST', '192.168.0.1'),
        port=int(os.getenv('RABBITMQ_PORT', 5672)),
        credentials=credentials
    ))
