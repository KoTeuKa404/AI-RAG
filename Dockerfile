FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Спочатку копіюємо лише файли, що описують залежності.
COPY pyproject.toml README.md LICENSE ./

# Створюємо мінімальний пакет, щоб pip зміг прочитати pyproject.
RUN mkdir -p app \
    && touch app/__init__.py \
    && python -m pip install --upgrade pip \
    && python -m pip install . \
    && rm -rf app

# Код копіюємо після встановлення залежностей.
# Зміни в Python-файлах більше не перевстановлюватимуть PyTorch.
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /models/huggingface \
    && chown -R appuser:appuser /app /models

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1"]