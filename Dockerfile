FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home appuser
USER appuser
EXPOSE 8080
ENTRYPOINT ["openpeoplerouter"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
