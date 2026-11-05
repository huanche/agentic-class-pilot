ARG NODE_IMAGE=node:22-alpine
FROM ${NODE_IMAGE}
USER 1001:1001
WORKDIR /app
COPY --chown=1001:1001 server.mjs /app/native-player/server.mjs
COPY --chown=1001:1001 public/ /app/native-player/public/
ENV PORT=3213
EXPOSE 3213
ENTRYPOINT ["node", "/app/native-player/server.mjs"]
