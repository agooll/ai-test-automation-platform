# Standard Python test runner sandbox image for TestTeller
# Tag: testteller-runner-python:3.11-v1
FROM python:3.11-slim

# Create unprivileged runner user
RUN groupadd -g 1000 runner && \
    useradd -u 1000 -g runner -m -s /bin/bash runner

# Support both repo-root context and docker/ context
COPY requirements.lock* docker/requirements.lock* /tmp/
RUN if [ -f /tmp/requirements.lock ]; then \
        pip install --no-cache-dir -r /tmp/requirements.lock; \
    elif [ -f /tmp/docker/requirements.lock ]; then \
        pip install --no-cache-dir -r /tmp/docker/requirements.lock; \
    fi && rm -rf /tmp/requirements.lock /tmp/docker

WORKDIR /workspace
RUN chown runner:runner /workspace
USER runner

CMD ["pytest", "-q"]
