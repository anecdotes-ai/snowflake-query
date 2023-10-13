FROM python:3.8-slim

RUN apt-get update && \
    apt-get install -y git && \
    python3 -m pip install --upgrade pip

# Configure environments vars. Overriden by GitHub Actions
ENV INPUT_SNOWFLAKE_ACCOUNT=
ENV INPUT_SNOWFLAKE_USERNAME=
ENV INPUT_SNOWFLAKE_PASSWORD=
ENV INPUT_SNOWFLAKE_WAREHOUSE=
ENV INPUT_QUERIES=
ENV APP_DIR=/app

WORKDIR ${APP_DIR}

# setup python environ
COPY ./requirements.txt ${APP_DIR}
RUN pip install -r ${APP_DIR}/requirements.txt

# copy app files
COPY . ./
RUN useradd -ms /bin/bash anecdotes
RUN chown -R anecdotes:anecdotes /app
USER anecdotes
# command to run in container start
CMD python ${APP_DIR}/main.py
