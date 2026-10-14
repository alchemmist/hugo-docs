FROM ghcr.io/gohugoio/hugo:v0.167.0 AS build
USER root
WORKDIR /src
COPY go.mod go.sum hugo.toml ./
RUN hugo mod graph
COPY --chown=0:0 . .
RUN hugo --source exampleSite --minify --destination /tmp/public \
    && test -f /tmp/public/hugo-content/lib/mermaid.js \
    && test -f /tmp/public/hugo-content/lib/mathjax/tex-svg.js \
    && test -f /tmp/public/hugo-content/lib/zoom.js

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /tmp/public /usr/share/nginx/html
RUN nginx -t
EXPOSE 8080
