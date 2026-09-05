# Standard Python test runner sandbox image for TestTeller
# Tag: testteller-runner-python:3.11-v1
FROM python:3.11-slim

# Create unprivileged runner user
RUN groupadd -g 1000 runner && \
    useradd -u 1000 -g runner -m -s /bin/bash runner

# Install deterministic pinned dependencies
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir -r /tmp/requirements.lock && \
    rm -f /tmp/requirements.lock

WORKDIR /workspace
RUN chown runner:runner /workspace
USER runner

CMD ["pytest", "-q"]
