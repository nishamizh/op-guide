"""Run one real embedding call and one real answer call when OPENAI_API_KEY is set."""

from app.config import get_settings
from app.db import session_scope
from app.ingestion.embeddings import embed_texts
from app.models import DocumentChunk


def main() -> int:
    settings = get_settings()
    if not settings.openai_configured():
        print("OPENAI_API_KEY is not set. Live embedding and answer calls were not performed.")
        return 2
    from openai import OpenAI

    with session_scope() as db:
        chunk = db.query(DocumentChunk).filter(DocumentChunk.section_id == "r200-e104").first()
    if chunk is None:
        print("Demo chunk r200-e104 is not indexed. Seed the database first.")
        return 3
    vectors, model = embed_texts([chunk.content[:1000]])
    print(f"embedding_model={model} dimensions={len(vectors[0])}")
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "Answer only from the manual excerpt. Say that the equipment is fictional demo data.",
            },
            {
                "role": "user",
                "content": f"What does E104 mean?\n\nExcerpt:\n{chunk.content[:1500]}",
            },
        ],
    )
    print(response.choices[0].message.content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
