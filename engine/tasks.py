from langchain_text_splitters import RecursiveCharacterTextSplitter
import nltk
from nltk.tokenize import sent_tokenize
import uuid
import pika
import os

def nltk_smart_chunk(input_text, chunk_size=1024, chunk_overlap=128, min_chunk_size=100):
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
                    overlap_buffer = full_chunk[-chunk_overlap:]
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
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
        add_start_index=True
    )
    chunks = splitter.split_text(input_text)
    return [{"id": str(uuid.uuid4()), "text": chunk} for chunk in chunks]

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
