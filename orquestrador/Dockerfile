FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
# RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 --retries=5 -r requirements.txt

COPY . .

ENV FLASK_APP=app.py
ENV FLASK_RUN_PORT=5000
ENV FLASK_ENV=development

EXPOSE 5000

CMD ["python", "app.py"]