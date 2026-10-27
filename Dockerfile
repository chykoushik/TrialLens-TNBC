FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
ENV VITE_PUBLIC_DEMO=1
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
COPY requirements-demo.lock.txt ./
RUN pip install --no-cache-dir -r requirements-demo.lock.txt
COPY backend/app/ ./backend/app/
COPY backend/public_demo.py ./backend/public_demo.py
COPY backend/serve_public.py ./backend/serve_public.py
COPY LICENSE THIRD_PARTY_NOTICES.txt ./
COPY third_party/ ./third_party/
COPY --from=frontend /app/frontend/dist/ ./frontend/dist/
COPY third_party/licenses/ ./frontend/dist/assets/licenses/
RUN useradd --uid 10001 --create-home demo
USER demo
EXPOSE 8080
CMD ["python", "-B", "-m", "backend.serve_public"]
