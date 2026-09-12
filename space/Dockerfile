FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libraries needed by OpenCV / Docling.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-space.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt -r requirements-space.txt

COPY homework_agent ./homework_agent
COPY data ./data
COPY demo.py ./
COPY app.py ./

# Warm up Docling's local OCR models at build time so the first request
# doesn't pay the download cost.
RUN python -c "from homework_agent import ocr; print(ocr.extract_printed('data/samples/science_homework.png')[:120])"

EXPOSE 7860

CMD ["python", "app.py"]
