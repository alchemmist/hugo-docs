FROM node:22.16.0-alpine AS frontend
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY editor ./editor
RUN npm run build

FROM ghcr.io/gohugoio/hugo:v0.167.0 AS template
USER root
WORKDIR /src
COPY go.mod go.sum hugo.toml ./
COPY layouts ./layouts
COPY assets ./assets
COPY static ./static
COPY i18n ./i18n
COPY archetypes ./archetypes
COPY runtime-site ./runtime-site
COPY --from=frontend /src/assets/wiki-editor.js ./assets/wiki-editor.js
RUN cd runtime-site && hugo mod vendor && hugo --minify --destination /tmp/public

FROM python:3.12-slim
ARG TARGETARCH
ARG HUGO_VERSION=0.167.0
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client ca-certificates curl \
    && cd /tmp \
    && curl -fsSL --retry 3 -o hugo.tar.gz "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_${HUGO_VERSION}_linux-${TARGETARCH}.tar.gz" \
    && curl -fsSL --retry 3 -o checksums.txt "https://github.com/gohugoio/hugo/releases/download/v${HUGO_VERSION}/hugo_${HUGO_VERSION}_checksums.txt" \
    && grep " hugo_${HUGO_VERSION}_linux-${TARGETARCH}.tar.gz$" checksums.txt | sed 's|  .*|  hugo.tar.gz|' | sha256sum --check \
    && tar -xzf hugo.tar.gz -C /usr/local/bin hugo \
    && rm hugo.tar.gz checksums.txt \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home wiki && mkdir /data && chown wiki:wiki /data
WORKDIR /app/runtime
COPY runtime/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY runtime/*.py ./
COPY --from=template /src/runtime-site /opt/wiki
USER 1000:1000
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LIVE_MODE=true LIVE_TEMPLATE_DIR=/opt/wiki WIKI_DATA_DIR=/data CONTENT_PREFIX=content
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-proxy-headers"]
