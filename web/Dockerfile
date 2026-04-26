# syntax=docker/dockerfile:1.7
FROM node:20-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:stable-alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
# Default nginx port
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
