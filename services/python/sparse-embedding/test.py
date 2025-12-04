import asyncio
from fastembed import SparseTextEmbedding, SparseEmbedding

async def test():
    models = SparseTextEmbedding.list_supported_models()
    print(models)

if __name__ == "__main__":
    asyncio.run(test())