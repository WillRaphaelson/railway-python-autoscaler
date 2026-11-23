FROM python:3.13-slim
WORKDIR /app
COPY api.py autoscaler.py policy.py load.py dashboard.html ./
ENV PYTHONUNBUFFERED=1 PORT=8080
RUN useradd --uid 10001 --create-home app
USER app
EXPOSE 8080
CMD ["python", "api.py"]
