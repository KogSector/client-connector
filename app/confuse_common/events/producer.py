"""
Kafka Event Producer

A generic event producer that works with any event type.
"""

import logging
from typing import Optional, Any
from pydantic import BaseModel
from confluent_kafka import Producer

from .config import KafkaConfig, ConfigError

logger = logging.getLogger(__name__)


class ProducerError(Exception):
    """Producer error"""
    pass


class EventProducer:
    """Event producer for publishing events to Kafka"""
    
    def __init__(self, config: Optional[KafkaConfig] = None):
        """
        Create a new event producer
        
        Args:
            config: Kafka configuration. If None, will be loaded from environment.
        """
        self.config = config or KafkaConfig.from_env()
        self._producer: Optional[Producer] = None
    
    @classmethod
    def from_env(cls) -> "EventProducer":
        """Create a new event producer from environment configuration"""
        return cls(KafkaConfig.from_env())
    
    @property
    def producer(self) -> Producer:
        """Get or create the underlying Kafka producer"""
        if self._producer is None:
            producer_config = self.config.to_producer_config()
            self._producer = Producer(producer_config)
            logger.info(
                f"Created Kafka producer for {self.config.bootstrap_servers} "
                f"({self.config.client_id})"
            )
        return self._producer
    
    def wait_until_ready(self, timeout: int = 300) -> None:
        """
        Wait synchronously until Kafka is fully available.
        Uses AdminClient to fetch cluster metadata.
        """
        from confluent_kafka.admin import AdminClient
        import time
        
        logger.info(f"Waiting up to {timeout}s for Kafka to be ready at {self.config.bootstrap_servers}...")
        start_time = time.time()
        admin_config = self.config.to_producer_config()
        
        admin_client = AdminClient(admin_config)
        
        attempt = 1
        while True:
            try:
                metadata = admin_client.list_topics(timeout=5.0)
                if metadata and metadata.brokers:
                    logger.info("Kafka is healthy and ready to accept connections.")
                    return
            except Exception as e:
                logger.debug(f"Kafka health check attempt {attempt} failed: {e}")
            
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise ProducerError(f"Kafka failed to become ready after {timeout} seconds.")
            
            attempt += 1
            time.sleep(2.0)
            
    def publish(self, event: BaseModel) -> None:
        """
        Publish an event to its designated topic
        
        The event must be a Pydantic model with a static topic() method.
        """
        topic = event.topic() if hasattr(event, 'topic') else 'unknown'
        self.publish_to_topic(event, topic)
    
    def publish_to_topic(
        self,
        event: BaseModel,
        topic: str,
        key: Optional[str] = None,
    ) -> None:
        """
        Publish an event to a specific topic
        
        Args:
            event: Pydantic model to publish
            topic: Kafka topic name
            key: Optional message key
        """
        payload = event.model_dump_json()
        
        logger.debug(f"Publishing event to topic '{topic}': {len(payload)} bytes")
        
        self.producer.produce(
            topic=topic,
            value=payload.encode('utf-8'),
            key=key.encode('utf-8') if key else None,
            callback=self._delivery_callback,
        )
        
        # Trigger delivery reports
        self.producer.poll(0)

    def publish_with_retry_to_topic(
        self,
        event: BaseModel,
        topic: str,
        key: Optional[str] = None,
        retries: int = 3,
        dlq_topic: Optional[str] = None,
    ) -> None:
        """
        Publish an event with retries and optional DLQ fallback.
        Retries use exponential backoff starting at 0.5s.
        """
        last_err: Optional[Exception] = None

        for attempt in range(retries):
            try:
                self.publish_to_topic(event, topic, key=key)
                # Give producer a chance to process delivery report
                self.producer.poll(0)
                return
            except Exception as e:
                last_err = e
                delay = (2 ** attempt) * 0.5
                logger.warning(f"Publish attempt {attempt+1} failed for {topic}, retrying in {delay}s: {e}")
                import time
                time.sleep(delay)

        logger.error(f"Failed to publish event to {topic} after {retries} attempts: {last_err}")

        final_dlq = dlq_topic or (f"{topic}.dlq" if topic else None)
        if final_dlq:
            try:
                envelope = {
                    "failedTopic": topic,
                    "failedAt": int(__import__('time').time() * 1000),
                    "error": str(last_err),
                    "event": event.model_dump(),
                }
                # Use publish_raw to send JSON envelope
                import json
                self.publish_raw(final_dlq, json.dumps(envelope), key=key)
                self.producer.poll(0)
                logger.info(f"Published failure envelope to DLQ {final_dlq}")
            except Exception as dlq_err:
                logger.exception("Failed to publish to DLQ", exc_info=dlq_err)

        # Raise original error for caller handling
        if last_err:
            raise ProducerError(str(last_err))
    
    def publish_raw(
        self,
        topic: str,
        value: str,
        key: Optional[str] = None,
    ) -> None:
        """
        Publish a raw string value to a topic
        
        Args:
            topic: Kafka topic name
            value: Raw string value
            key: Optional message key
        """
        self.producer.produce(
            topic=topic,
            value=value.encode('utf-8'),
            key=key.encode('utf-8') if key else None,
            callback=self._delivery_callback,
        )
        self.producer.poll(0)
    
    def flush(self, timeout: float = 30.0) -> int:
        """
        Wait for all buffered messages to be delivered
        
        Args:
            timeout: Maximum time to wait in seconds
            
        Returns:
            Number of messages still in queue (0 if all delivered)
        """
        return self.producer.flush(timeout)
    
    def _delivery_callback(self, err: Any, msg: Any) -> None:
        """Callback for delivery reports"""
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.debug(
                f"Message delivered to {msg.topic()} "
                f"[{msg.partition()}] @ {msg.offset()}"
            )
    
    def __enter__(self) -> "EventProducer":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.flush()
