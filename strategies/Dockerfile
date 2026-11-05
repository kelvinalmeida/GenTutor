# Alterado de python:3.9 para python:3.11-slim para compatibilidade e leveza
FROM python:3.11-slim

# Definir o diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema necessárias para compilar pacotes (como psycopg2)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar os arquivos do projeto
COPY . .

# Instalar as dependências
RUN pip install --upgrade pip
RUN pip install --no-cache-dir --timeout=120 --retries=5 -r requirements.txt

# Variáveis de ambiente
ENV FLASK_APP=app.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=5003
ENV FLASK_ENV=development

# Expor a porta
EXPOSE 5003

# Rodar o aplicativo
CMD ["flask", "run", "--host=0.0.0.0"]