"""
Kafka Event Producer for Client Connector.
"""
import structlog
from typing import Optional
from confuse_common.events import EventProducer, KafkaConfig
from app.config import get_settings

logger = structlog.get_logger()

_producer: Optional[EventProducer] = None

def init_event_producer() -> EventProducer:
    """Initialize the global Kafka event producer."""
    global _producer
    settings = get_settings()
    
    try:
        config = KafkaConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            client_id=settings.kafka_client_id,
            security_protocol=settings.kafka_security_protocol,
            sasl_mechanism=settings.kafka_sasl_mechanism,
            sasl_username=settings.kafka_sasl_username,
            sasl_password=settings.kafka_sasl_password,
        )
        _producer = EventProducer(config=config)
        # Accessing the producer property triggers connection
        _ = _producer.producer
        logger.info("Kafka event producer initialized", 
                    bootstrap_servers=settings.kafka_bootstrap_servers,
                    client_id=settings.kafka_client_id)
        return _producer
    except Exception as e:
        logger.error("Failed to initialize Kafka event producer", error=str(e))
        return None

def get_event_producer() -> Optional[EventProducer]:
    """Get the initialized Kafka event producer."""
    return _producer

async def close_event_producer():
    """Close the Kafka event producer."""
    global _producer
    if _producer:
        logger.info("Closing Kafka event producer")
        _producer.flush()
        _producer = None
