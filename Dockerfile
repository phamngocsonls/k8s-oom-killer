FROM python:3.12-alpine

ADD requirements.txt ./

RUN pip install --upgrade pip

RUN pip install -r requirements.txt

RUN rm -f ./requirements.txt

WORKDIR ./src

COPY main.py .

CMD ["python","-u","main.py"]