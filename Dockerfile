FROM python:3.10-slim

RUN apt-get update && \
    apt-get install -y git && \
    python3 -m pip install --upgrade pip

# Configure environments vars. Overriden by GitHub Actions
ENV INPUT_SNOWFLAKE_ACCOUNT=
ENV INPUT_SNOWFLAKE_USERNAME=
ENV INPUT_SNOWFLAKE_PASSWORD=
ENV INPUT_SNOWFLAKE_PRIVATE_KEY=
ENV INPUT_SNOWFLAKE_WAREHOUSE=
ENV INPUT_QUERIES=
ENV APP_DIR=/app

WORKDIR ${APP_DIR}

# setup python environ
COPY ./requirements.txt ${APP_DIR}
RUN pip install -r ${APP_DIR}/requirements.txt

# copy app files
COPY . ./

# Gate the credential seam at build time. This repo's own Actions are disabled, so a workflow here
# would never fire — but a `docker` action builds its image on the runner inside the *consumer's*
# workflow, where Actions is enabled. So these run on every invocation, before any query reaches
# Snowflake, and a regression fails the caller's step instead of shipping silently.
RUN pip install --no-cache-dir pytest==7.4.4 && \
    pytest ${APP_DIR}/test_credentials.py -q && \
    pip uninstall -y pytest
RUN useradd -ms /bin/bash anecdotes
RUN chown -R anecdotes:anecdotes /app
USER anecdotes
# command to run in container start
CMD python ${APP_DIR}/main.py
