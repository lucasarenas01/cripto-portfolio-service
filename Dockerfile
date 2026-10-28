# Imagen base ligera de Python
FROM python:3.11-slim

# Evitar que Python genere archivos .pyc y forzar salida inmediata por consola
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Directorio de trabajo interno
WORKDIR /app

# Instalar dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY main.py .

# Comando de ejecución
CMD ["python", "main.py"]