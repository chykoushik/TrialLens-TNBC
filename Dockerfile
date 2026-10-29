FROM node:22-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY results/prioritization/coherent/20261025-imperfect-analysis-v1/report.md /app/results/prioritization/coherent/20261025-imperfect-analysis-v1/report.md
COPY results/prioritization/sensitivity/20261025-final/report.md /app/results/prioritization/sensitivity/20261025-final/report.md
ENV VITE_PUBLIC_DEMO=0
ENV VITE_PUBLIC_RESEARCH=1
ENV VITE_API_BASE_URL=/api
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV TRIALLENS_BYOK_ENABLED=0
ENV TRIALLENS_PUBLIC_RESEARCH=1
COPY requirements-demo.lock.txt ./
RUN pip install --no-cache-dir -r requirements-demo.lock.txt
COPY backend/app/ ./backend/app/
COPY backend/public_demo.py ./backend/public_demo.py
COPY backend/serve_public.py ./backend/serve_public.py
COPY backend/research_public.py ./backend/research_public.py
COPY research/ ./research/
COPY results/ ./results/
COPY data/raw/trials/ ./data/raw/trials/
RUN mkdir -p data/raw/trials && chown -R 10001:10001 data
COPY LICENSE THIRD_PARTY_NOTICES.txt ./
COPY third_party/ ./third_party/
COPY --from=frontend /app/frontend/dist/ ./frontend/dist/
COPY third_party/licenses/ ./frontend/dist/assets/licenses/
RUN useradd --uid 10001 --create-home demo
USER demo
EXPOSE 8080
CMD ["python", "-B", "-m", "backend.serve_public"]
