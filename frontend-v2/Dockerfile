FROM node:20-alpine

WORKDIR /app

COPY package.json ./

RUN npm install --legacy-peer-deps

COPY . .

ARG VITE_API_BASE_URL=http://localhost:3456
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV PORT=5173

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
