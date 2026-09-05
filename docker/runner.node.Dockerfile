# Standard Node.js test runner sandbox image for TestTeller
FROM node:18-slim

# Install standard jest test runner globally
RUN npm install -g jest ts-jest typescript @types/jest

WORKDIR /workspace
USER node

CMD ["jest"]
