FROM python:3.12-slim
WORKDIR /app

# CPU-only torch keeps the image ~1.5 GB instead of ~5 GB
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
COPY requirements.txt .
RUN grep -v -i "^torch" requirements.txt > req.txt && pip install --no-cache-dir -r req.txt

# bake the model into the image so cold starts don't download it
ENV HF_HOME=/app/hf DISABLE_SAFETENSORS_CONVERSION=1
RUN python -c "from transformers import pipeline; pipeline('text-classification', model='cardiffnlp/xlm-roberta-base-sentiment-multilingual')"

COPY app ./app
COPY static ./static
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
