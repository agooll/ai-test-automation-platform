# Standard Python test runner sandbox image for TestTeller
FROM python:3.11-slim

# Create unprivileged runner user
RUN groupadd -g 1000 runner && \
    useradd -u 1000 -g runner -m -s /bin/bash runner

# Install essential test runners and reporting tools
RUN pip install --no-cache-dir \
    pytest>=8.0.0 \
    pytest-asyncio>=0.23.0 \
    pytest-timeout>=2.2.0 \
    pytest-json-report>=1.5.0 \
    playwright>=1.40.0

WORKDIR /workspace
USER runner

CMD ["pytest", "-q"]
