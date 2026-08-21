FROM node:20-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci || npm install

COPY . .

EXPOSE 5173
# --host so the dev server is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
