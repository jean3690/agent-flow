FROM node:22-alpine AS build

WORKDIR /app
COPY ts-backend/package.json ts-backend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY ts-backend/tsconfig.json ./
COPY ts-backend/src ./src
RUN npm run build

FROM node:22-alpine

WORKDIR /app
ENV NODE_ENV=production \
    TZ=Asia/Shanghai \
    SKILLS_PATH=/app/skills \
    AGENTFLOW_SCHEMA_SQL=/app/schema.sql

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY ts-backend/package.json ./
COPY backend/src/main/resources/skills ./skills
COPY backend/src/main/resources/schema.sql ./schema.sql

EXPOSE 8084
CMD ["node", "dist/src/main.js"]
