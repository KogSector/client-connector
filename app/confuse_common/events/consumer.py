"""
Kafka Event Consumer

A generic event consumer with handler protocol for processing events.
"""

import logging
from typing import Optional, Protocol, List, Any
from threading import Event
from pydantic import BaseModel
from confluent_kafka import Consumer, KafkaError, KafkaException

from .config import KafkaConfig, ConfigError

logger = logging.getLogger(__name__)


class ConsumerError(Exception):
    """Consumer error"""
    pass


class EventHandler(Protocol):
    """Protocol for event handlers"""
    
    def handle(self, topic: str, payload: bytes) -> None:
        """
        Handle a raw message from Kafka
        
        Implementations should deserialize the payload and process the event.
        """
        ...
    
    def handle_error(self, topic: str, error: Exception, payload: Optional[bytes] = None) -> None:
        """
        Handle deserialization or processing errors
        
        Default implementations can send to DLQ.
        """
        ...


class EventConsumer:
    """Event consumer for subscribing to Kafka topics"""
    
    def __init__(self, config: Optional[KafkaConfig] = None):
        """
        Create a new event consumer
        
        Args:
            config: Kafka configuration. If None, will be loaded from environment.
        """
        self.config = config or KafkaConfig.from_env()
        self._consumer: Optional[Consumer] = None
        self._shutdown = Event()
    
    @classmethod
    def from_env(cls) -> "EventConsumer":
        """Create a new event consumer from environment configuration"""
        return cls(KafkaConfig.from_env())
    
    @property
    def consumer(self) -> Consumer:
        """Get or create the underlying Kafka consumer"""
        if self._consumer is None:
            consumer_config = self.config.to_consumer_config()
            self._consumer = Consumer(consumer_config)
            logger.info(
                f"Created Kafka consumer for {self.config.bootstrap_servers} "
                f"(group: {self.config.group_id})"
            )
        return self._consumer
    
    def subscribe(self, topics: List[str]) -> None:
        """Subscribe to one or more topics"""
        self.consumer.subscribe(topics)
        logger.info(f"Subscribed to topics: {topics}")
    
    def run(self, handler: EventHandler, poll_timeout: float = 1.0) -> None:
        """
        Start consuming messages with the provided handler
        
        This method runs until shutdown is called or an unrecoverable error occurs.
        
        Args:
            handler: EventHandler implementation
            poll_timeout: Timeout for polling in seconds
        """
        logger.info("Starting consumer loop")
        
        try:
            while not self._shutdown.is_set():
                msg = self.consumer.poll(poll_timeout)
                
                if msg is None:
                    continue
                
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(
                            f"End of partition reached: {msg.topic()} "
                            f"[{msg.partition()}] @ {msg.offset()}"
                        )
                    else:
                        logger.error(f"Kafka error: {msg.error()}")
                    continue
                
                try:
                    handler.handle(msg.topic(), msg.value())
                    
                    # Commit offset after successful processing
                    self.consumer.commit(msg)
                    
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    handler.handle_error(msg.topic(), e, msg.value())
                    
        except KeyboardInterrupt:
            logger.info("Received keyboard interrupt, shutting down")
        finally:
            self.close()
    
    def shutdown(self) -> None:
        """Signal the consumer to shut down"""
        logger.info("Shutdown requested")
        self._shutdown.set()
    
    def close(self) -> None:
        """Close the consumer"""
        if self._consumer is not None:
            self._consumer.close()
            self._consumer = None
            logger.info("Consumer closed")
    
    def __enter__(self) -> "EventConsumer":
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


def deserialize_event(event_class: type[BaseModel], payload: bytes) -> BaseModel:
    """
    Helper function to deserialize a message payload
    
    Args:
        event_class: Pydantic model class to deserialize into
        payload: Raw bytes from Kafka
        
    Returns:
        Deserialized event
    """
    return event_class.model_validate_json(payload)
