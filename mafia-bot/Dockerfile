FROM python:3.12-slim
WORKDIR /app
COPY bot.py engine.py payments.py ./
COPY assets/ ./assets/
RUN useradd --create-home bot && mkdir /app/data && chown bot:bot /app/data
USER bot
CMD ["python", "bot.py"]
