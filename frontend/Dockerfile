# Сборка SPA и раздача статики nginx.
#
# Два этапа: node нужен только для сборки, в финальный образ он не попадает —
# иначе в проде висел бы лишний рантайм с полным node_modules.

FROM node:22-alpine AS build

WORKDIR /app

# Зависимости ставятся отдельным слоем: правка исходников не должна
# приводить к повторному npm ci.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template

# Значение по умолчанию для compose; в Kubernetes переопределяется переменной.
# Фильтр обязателен: без него envsubst подставит любую переменную окружения
# и может съесть служебные переменные nginx вроде $host и $scheme.
ENV API_UPSTREAM=http://api:8000     NGINX_ENVSUBST_FILTER=API_UPSTREAM
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# Проба готовности для compose и Kubernetes.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
