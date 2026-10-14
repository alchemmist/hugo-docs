FROM ghcr.io/gohugoio/hugo:v0.167.0 AS build
USER root
WORKDIR /src
COPY . .
RUN hugo --minify --destination /tmp/public

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /tmp/public /usr/share/nginx/html
RUN nginx -t
EXPOSE 8080
