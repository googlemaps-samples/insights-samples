import sys
import os
import json
import logging
from google.cloud import pubsub_v1
from google.cloud import bigquery

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RMI_PubSub_Consumer")

PROJECT_ID = os.environ.get("PROJECT_ID", "my-project-id")
SUBSCRIPTION_ID = os.environ.get("SUBSCRIPTION_ID", "rmi-realtime-sub")
BQ_DATASET = os.environ.get("BQ_DATASET", "rmi_realtime")
BQ_TABLE = os.environ.get("BQ_TABLE", "recent_roads_live")
MAX_MESSAGES = int(os.environ.get("MAX_MESSAGES", "0"))  # 0 = infinite daemon, >0 stops after N messages for testing

# Counter for test mode
processed_message_count = 0

# Initialize Clients
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
bq_client = bigquery.Client(project=PROJECT_ID)

# In-memory de-duplication cache (sliding window of recently seen composite keys)
processed_cache = set()

def insert_to_bigquery(rows):
    """Inserts raw JSON rows into BigQuery streamingly."""
    table_ref = bq_client.dataset(BQ_DATASET).table(BQ_TABLE)
    errors = bq_client.insert_rows_json(table_ref, rows)
    if errors:
        logger.error(f"BigQuery write errors encountered: {errors}")
    else:
        logger.info(f"Streamed {len(rows)} records to BigQuery.")

def callback(message):
    """Asynchronous subscriber callback handling incoming payloads."""
    try:
        # 1. Parse the incoming payload (supports both JSON and Binary Protobuf)
        try:
            # Try JSON parsing first
            payload = json.loads(message.data.decode("utf-8"))
            route_id = payload.get("selected_route_id")
            display_name = payload.get("display_name")
            
            # Evolved fields (effective October 8, 2026)
            has_road_closure = payload.get("has_road_closure", False)
            retrieval_timestamp = payload.get("retrieval_timestamp")
            
            # Duration parsing with COALESCE fallback to legacy travel_duration
            travel_duration_payload = payload.get("travel_duration") or {}
            duration_in_seconds = payload.get("duration_in_seconds")
            if duration_in_seconds is None and not has_road_closure:
                duration_in_seconds = travel_duration_payload.get("duration_in_seconds")
                
            static_duration_in_seconds = payload.get("static_duration_in_seconds")
            if static_duration_in_seconds is None:
                static_duration_in_seconds = travel_duration_payload.get("static_duration_in_seconds")

            # Offset-based speed readings (new as of Oct 8, 2026; supports TRAFFIC_JAM_HEAVY)
            speed_reading_offsets = payload.get("speed_reading_offsets", [])
            
            # Legacy speed reading intervals (deprecated; retained for backward compatibility)
            speed_reading_intervals = payload.get("speed_reading_intervals", [])

            # Parse retrieval_time for legacy compatibility and timestamp reconstruction
            retrieval_time_payload = payload.get("retrieval_time", {})
            if isinstance(retrieval_time_payload, dict):
                retrieval_time_seconds = retrieval_time_payload.get("seconds")
                retrieval_time_nanos = retrieval_time_payload.get("nanos", 0)
            elif isinstance(retrieval_time_payload, (int, float)):
                retrieval_time_seconds = int(retrieval_time_payload)
                retrieval_time_nanos = int((retrieval_time_payload - retrieval_time_seconds) * 1e9)
            else:
                retrieval_time_seconds = None
                retrieval_time_nanos = None

            route_geometry = payload.get("route_geometry")
            road_segment_ids = payload.get("road_segment_ids", [])
            
        except (unicode if sys.version_info[0] < 3 else str, ValueError, AttributeError, TypeError, KeyError):
            # Fallback to Protobuf deserialization if payload is binary
            from google.maps.roadsmanagement.insights.v1 import rmi_pb2
            proto_msg = rmi_pb2.RoadsInformation()
            proto_msg.ParseFromString(message.data)
            route_id = proto_msg.selected_route_id
            display_name = proto_msg.display_name
            
            # Oct 8, 2026 evolved fields
            has_road_closure = getattr(proto_msg, "has_road_closure", False)
            retrieval_timestamp = getattr(proto_msg, "retrieval_timestamp", None)
            
            # Duration parsing with COALESCE fallback
            if hasattr(proto_msg, "duration_in_seconds") and proto_msg.duration_in_seconds != 0.0:
                duration_in_seconds = proto_msg.duration_in_seconds
            elif proto_msg.HasField("travel_duration"):
                duration_in_seconds = proto_msg.travel_duration.duration_in_seconds
            else:
                duration_in_seconds = None if has_road_closure else 0.0

            if hasattr(proto_msg, "static_duration_in_seconds") and proto_msg.static_duration_in_seconds != 0.0:
                static_duration_in_seconds = proto_msg.static_duration_in_seconds
            elif proto_msg.HasField("travel_duration"):
                static_duration_in_seconds = proto_msg.travel_duration.static_duration_in_seconds
            else:
                static_duration_in_seconds = None

            # Legacy retrieval_time if present
            if proto_msg.HasField("retrieval_time"):
                retrieval_time_seconds = proto_msg.retrieval_time.seconds
                retrieval_time_nanos = proto_msg.retrieval_time.nanos
            else:
                retrieval_time_seconds = None
                retrieval_time_nanos = None

            route_geometry = proto_msg.route_geometry
            road_segment_ids = list(proto_msg.road_segment_ids)
            
            # Speed reading offsets (new as of Oct 8, 2026)
            speed_reading_offsets = []
            if hasattr(proto_msg, "speed_reading_offsets"):
                for offset in proto_msg.speed_reading_offsets:
                    speed_reading_offsets.append({
                        "start_offset": offset.start_offset,
                        "end_offset": offset.end_offset,
                        "speed": offset.speed
                    })

            # Legacy speed reading intervals
            speed_reading_intervals = []
            for interval in proto_msg.speed_reading_intervals:
                coords = [{"latitude": c.latitude, "longitude": c.longitude} for c in interval.interval_coordinates]
                speed_reading_intervals.append({
                    "speed": interval.speed,
                    "interval_coordinates": coords
                })
        
        # 2. De-duplication check using composite key
        dedup_time = retrieval_timestamp or (str(retrieval_time_seconds) if retrieval_time_seconds is not None else "unknown")
        dedup_key = f"{route_id}_{dedup_time}"
        if dedup_key in processed_cache:
            logger.info(f"Duplicate event detected for key: {dedup_key}. Skipping.")
            message.ack()
            return
            
        # 3. Process the message
        logger.info(f"Processing route_id={route_id} ts={dedup_time} closure={has_road_closure}")
        
        # Prepare BQ row matching roads_information_landing.json
        bq_row = {
            "selected_route_id": route_id,
            "display_name": display_name,
            "speed_reading_offsets": speed_reading_offsets,
            "duration_in_seconds": duration_in_seconds,
            "static_duration_in_seconds": static_duration_in_seconds,
            "retrieval_timestamp": retrieval_timestamp,
            "has_road_closure": has_road_closure,
            "speed_reading_intervals": speed_reading_intervals,
            "travel_duration": {
                "duration_in_seconds": duration_in_seconds,
                "static_duration_in_seconds": static_duration_in_seconds
            } if (duration_in_seconds is not None or static_duration_in_seconds is not None) else None,
            "retrieval_time": {
                "seconds": retrieval_time_seconds,
                "nanos": retrieval_time_nanos
            } if retrieval_time_seconds is not None else None,
            "route_geometry": route_geometry,
            "road_segment_ids": road_segment_ids
        }
        
        # 4. Stream to BigQuery
        insert_to_bigquery([bq_row])
        
        # 5. Cache de-duplication key
        processed_cache.add(dedup_key)
        # Keep cache bounded
        if len(processed_cache) > 10000:
            processed_cache.pop()
            
        # 6. Acknowledge message delivery
        message.ack()

        global processed_message_count
        processed_message_count += 1
        if MAX_MESSAGES > 0 and processed_message_count >= MAX_MESSAGES:
            logger.info(f"Reached MAX_MESSAGES limit ({MAX_MESSAGES}). Stopping stream...")
            streaming_pull_future.cancel()
        
    except Exception as e:
        logger.error(f"Error handling message payload: {e}")
        # Nack message to trigger redelivery
        message.nack()

# Configure Flow Control (Backpressure Management)
flow_control = pubsub_v1.types.FlowControl(
    max_messages=100,  # Limits memory overhead
    max_bytes=50 * 1024 * 1024  # 50MB Max in-flight
)

# Start Subscription Stream
streaming_pull_future = subscriber.subscribe(
    subscription_path,
    callback=callback,
    flow_control=flow_control
)

logger.info(f"Active. Listening for RMI stream events on {subscription_path}...")

# Keep thread running
try:
    streaming_pull_future.result()
except KeyboardInterrupt:
    streaming_pull_future.cancel()
    logger.info("Subscription listener terminated by operator.")