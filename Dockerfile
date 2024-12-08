FROM python:3.13.1-bookworm
WORKDIR /app
COPY ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY . .
CMD ["gunicorn", "--threads", "4", "--bind", "0.0.0.0:80", "main:app"]
