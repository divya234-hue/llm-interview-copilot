FROM node:22-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
EXPOSE 5173
ARG VITE_API_BASE_URL=http://localhost:8000/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:5173/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"]
