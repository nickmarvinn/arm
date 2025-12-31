FROM python:3.14

WORKDIR /app

COPY requirements.txt .

RUN pip install -r requirements.txt

COPY . .

COPY ./build ./build

EXPOSE 5000

#CMD ["python", "app.py"]

CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app"]