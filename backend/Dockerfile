FROM mcr.microsoft.com/playwright/python:v1.42.0-jammy

WORKDIR /srv/app

# Create unprivileged sandbox runner user
RUN groupadd -r testforge && useradd -r -g testforge -m -d /home/testforge testforge

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tests ./tests

RUN mkdir -p /srv/app/artifacts && chown -R testforge:testforge /srv/app

USER testforge
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
