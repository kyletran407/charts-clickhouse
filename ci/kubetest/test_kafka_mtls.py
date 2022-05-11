import pytest
from kubetest.client import TestClient
from kubetest.objects import Secret

from helpers.utils import (
    cleanup_k8s,
    create_namespace_if_not_exists,
    install_chart,
    exec_subprocess,
    is_posthog_healthy,
    wait_for_pods_to_be_ready,
)

VALUES_YAML = """
cloud: local

externalKafka:
  brokers:
    - "kafka-headless:9092"
  mtls:
    secretName: kafka-client-tls

#
# For the purpose of this test, let's disable service persistence
#
clickhouse:
  persistence:
    enabled: false
kafka:
  enabled: false
  persistence:
    enabled: false
pgbouncer:
  persistence:
    enabled: false
postgresql:
  persistence:
    enabled: false
redis:
  master:
    persistence:
      enabled: false
zookeeper:
  persistence:
    enabled: false
"""


def test_install(kube: TestClient):
    cleanup_k8s()
    create_namespace_if_not_exists()

    # Firstly, provision a Kafka deployment, with mtls enabled. We have the
    # kafka helm chart generate it's own CA and certificate to use for TLS
    exec_subprocess("""
      helm repo add bitnami https://charts.bitnami.com/bitnami && \
      helm upgrade --install \
        --namespace posthog \
        kafka bitnami/kafka \
        --version "16.2.10" \
        --set zookeeper.enabled=true \
        --set replicaCount=1 \
        --set auth.clientProtocol=mtls \
        --set auth.tls.autoGenerated=true \
        --set auth.tls.type=pem \
        --wait
    """)

    # We then pull out the generated cert and ca cert and use this ourselves
    # within the posthog deployment. Note that `tls` will have base64 encoding
    # already applied, which is a requirement for the PostHog app to parse
    # correctly.
    tls = kube.get_secrets(namespace="posthog")['kafka-0-tls']

    exec_subprocess(f"""
      kubectl create secret generic kafka-client-tls \
        --namespace posthog \
        --from-literal=ca.crt={tls.obj.data['ca.crt']} \
        --from-literal=tls.crt={tls.obj.data['ca.crt']} \
        --from-literal=tls.key={tls.obj.data['tls.key']}
    """)

    install_chart(VALUES_YAML)

    wait_for_pods_to_be_ready(kube)
