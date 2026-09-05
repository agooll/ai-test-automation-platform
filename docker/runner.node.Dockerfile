# Standard Node.js test runner sandbox image for TestTeller
# Tag: testteller-runner-node:18-v1
FROM node:18-slim

# Install pinned jest test runner and typescript dependencies globally
RUN npm install -g jest@29.7.0 ts-jest@29.1.5 typescript@5.4.5 @types/jest@29.5.12

WORKDIR /workspace
RUN chown node:node /workspace
USER node

CMD ["jest"]
