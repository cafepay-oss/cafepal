FROM python:3.7.7
WORKDIR /app

# install requirements
COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

# copy and setup project
COPY cafepal cafepal
COPY cafepay cafepay
COPY sms sms
COPY local_static local_static
COPY manage.py .
COPY start.sh .


RUN chmod +x start.sh

CMD ["./start.sh"]