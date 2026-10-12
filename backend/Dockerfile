FROM python:3.12-slim-trixie

RUN apt-get update \
 && apt-get install -y --no-install-recommends stockfish \
 && rm -rf /var/lib/apt/lists/*
# fail the build if the binary is missing; the build log prints the Stockfish version
RUN test -x /usr/games/stockfish && echo quit | /usr/games/stockfish | head -n1

ENV STOCKFISH_PATH=/usr/games/stockfish PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]