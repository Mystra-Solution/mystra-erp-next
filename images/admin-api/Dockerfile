# Admin API image with Docker SDK for dynamic frontend creation.
# Build with: docker build --build-arg BASE_IMAGE=custom:15 -t admin-api:15 -f images/admin-api/Dockerfile .
ARG BASE_IMAGE=frappe/erpnext:version-15
FROM ${BASE_IMAGE}

USER root
COPY images/admin-api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt
USER frappe
