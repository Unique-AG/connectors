import asyncio
import logging
from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.envconfig import ClientConfig
from app.config import settings
from app.activities import embed_sparse
from app.grpc_server import serve_grpc

load_dotenv()  # pyright: ignore[reportUnusedCallResult]


async def run_temporal_worker():
    logging.info("Starting Temporal worker...")
    
    connect_config = ClientConfig.load_client_connect_config()
    client = await Client.connect(**connect_config)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        activities=[embed_sparse],
    )

    logging.info("Temporal worker started")
    await worker.run()


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logging.info("Starting sparse embedding services...")
    logging.info(f"gRPC port: {settings.grpc_port}")
    logging.info(f"Temporal task queue: {settings.temporal_task_queue}")

    _ = await asyncio.gather(
        serve_grpc(port=settings.grpc_port),
        run_temporal_worker(),
    )


if __name__ == "__main__":
    asyncio.run(main())
