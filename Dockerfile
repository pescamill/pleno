# Public read-only demo of Pleno (Render, Hugging Face Spaces). The database is fetched at start-up.
FROM python:3.14-slim
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user deploy/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user pleno pleno
COPY --chown=user web web
COPY --chown=user deploy/arranque.py .
USER user
ENV PLENO_PUBLICO=1 PLENO_DB=/tmp/pleno.db PLENO_DB_REPO=pescamil/pleno-datos PYTHONUNBUFFERED=1
CMD ["python", "arranque.py"]
