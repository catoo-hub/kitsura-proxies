FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY src/ src/

# Создаем директорию для данных
RUN mkdir -p data

# Запускаем бота
CMD ["python", "-m", "src.main"]
