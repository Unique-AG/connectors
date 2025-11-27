import asyncio
import logging
from dotenv import load_dotenv
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.envconfig import ClientConfig
from app.config import settings
from app.activities import embed_sparse

# Load environment variables from .env file for Temporal client config
load_dotenv()  # pyright: ignore[reportUnusedCallResult]

async def main():
    logging.basicConfig(level=logging.INFO)

    connect_config = ClientConfig.load_client_connect_config()
    
    client = await Client.connect(**connect_config)

    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        activities=[embed_sparse],
    )

    print("Python worker started...")
    await worker.run()

if __name__ == "__main__":
    asyncio.run(main())
