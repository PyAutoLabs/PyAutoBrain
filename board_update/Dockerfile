FROM python:3.12-slim
WORKDIR /app
COPY board_update/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY board_update ./board_update
USER 65534:65534
EXPOSE 8080
# One worker is required: OAuth/session state intentionally lives only in memory.
# Do not enable access logs: callback query strings contain temporary OAuth codes.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "60", "board_update.app:create_app()"]
