FROM node:18-alpine

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json package-lock.json* ./

# Install dependencies
RUN npm install

# Copy application code
COPY . .

# Build argument for API URL
ARG VITE_API_BASE_URL=http://localhost:3456
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

# Expose port
EXPOSE 6789

# Start development server on port 6789
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "6789"]
