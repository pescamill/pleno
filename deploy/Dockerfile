# Hugging Face Space (Docker): read-only public demo of Pleno.
FROM python:3.14-slim
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
USER user
ENV PLENO_PUBLICO=1 PLENO_DB=/tmp/pleno.db PYTHONUNBUFFERED=1
EXPOSE 7860
CMD ["python", "arranque.py"]
