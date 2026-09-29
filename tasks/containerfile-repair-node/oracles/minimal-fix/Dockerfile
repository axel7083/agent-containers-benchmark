FROM node:latest
COPY . /app
RUN cd /app && npm install
EXPOSE 8080
CMD node /app/src/server.js
