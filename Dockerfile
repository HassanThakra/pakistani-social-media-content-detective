FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PORT=7860 TRUST_PROXY=1 SCALING_MAX_ROWS=300000
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY --chown=user requirements.txt .
RUN pip install -r requirements.txt
ARG WITH_MODEL=0
COPY --chown=user requirements-model.txt .
RUN if [ "$WITH_MODEL" = "1" ]; then pip install -r requirements-model.txt; fi
COPY --chown=user . .
USER user
# Download the model at build time so the first visitor does not wait (only when WITH_MODEL=1)
RUN if [ "$WITH_MODEL" = "1" ]; then python -c "from transformers import pipeline; pipeline('text-classification', model='cardiffnlp/twitter-xlm-roberta-base-sentiment')"; fi
EXPOSE 7860
CMD ["sh", "-c", "gunicorn -w ${WEB_WORKERS:-2} --threads 4 --timeout 120 -b 0.0.0.0:${PORT} app:app"]
