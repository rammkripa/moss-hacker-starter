"""Build the Moss indexes used by this voice agent.

Creates two indexes from the credentials in ``agent-py/.env.local``:

* the static ``knowledge`` index (RAG corpus), seeded from ``agent-py/knowledge.json``
* the ``memory`` index (per-user agentic memory), seeded with a single placeholder
  document so the index exists and can be loaded before the first runtime write.

Run from the repo root via ``pnpm moss:index`` (which invokes
``uv --directory agent-py run src/create_index.py``) once Moss credentials are set.
This script needs ``MOSS_PROJECT_ID`` / ``MOSS_PROJECT_KEY`` to run; without them it
exits with a clear message instead of contacting Moss.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from moss import DocumentInfo, MossClient

# Resolve paths relative to this file so the script works regardless of the
# current working directory. ``src/create_index.py`` -> parent.parent == agent-py/.
AGENT_DIR = Path(__file__).resolve().parent.parent
KNOWLEDGE_PATH = AGENT_DIR / "knowledge.json"
ENV_PATH = AGENT_DIR / ".env.local"

DEFAULT_MODEL_ID = "moss-minilm"
DEFAULT_KNOWLEDGE_INDEX = "knowledge"
DEFAULT_MEMORY_INDEX = "memory"
DEFAULT_EVENTS_INDEX = "events"

# Load environment variables from agent-py/.env.local.
load_dotenv(ENV_PATH)


def _load_knowledge_documents() -> list[DocumentInfo]:
    """Load knowledge.json into a list of Moss DocumentInfo entries."""
    if not KNOWLEDGE_PATH.exists():
        raise FileNotFoundError(f"Knowledge data file not found at {KNOWLEDGE_PATH}.")

    with KNOWLEDGE_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if not isinstance(data, list):
        raise ValueError("knowledge.json must be a list of document entries.")

    documents: list[DocumentInfo] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        doc_id = entry.get("id")
        text = entry.get("text")
        if not doc_id or not text:
            continue
        metadata = entry.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        # Moss metadata values must be strings.
        metadata = {str(k): str(v) for k, v in metadata.items()}
        documents.append(
            DocumentInfo(id=str(doc_id), text=str(text), metadata=metadata)
        )

    if not documents:
        raise ValueError("No valid documents were loaded from knowledge.json.")

    return documents


def _memory_seed_documents() -> list[DocumentInfo]:
    """A single placeholder doc so the memory index exists and loads cleanly.

    The agent's memory tools upsert real per-user documents at runtime (matching
    ``id`` upserts). This seed is filtered out at query time by its ``user_id``.
    """
    return [
        DocumentInfo(
            id="__seed__",
            text="(memory seed) placeholder document so the memory index can be loaded before the first write.",
            metadata={"user_id": "__seed__"},
        )
    ]


def _events_seed_documents() -> list[DocumentInfo]:
    """Placeholder so the events index exists and loads before the first ingest.

    Live mission events flow in at runtime through /api/mission/ingest, which
    writes to this index. The seed is filtered out at query time by its
    ``mission_id``.
    """
    return [
        DocumentInfo(
            id="__events_seed__",
            text="(events seed) placeholder document. No real events yet.",
            metadata={
                "mission_id": "__seed__",
                "event_type": "unknown",
                "urgency": "low",
                "confidence": "0.0",
                "timestamp": "1970-01-01T00:00:00Z",
                "location_guess": "",
                "source": "__seed__",
                "external_id": "",
                "raw_ref": "",
            },
        )
    ]


async def build_indexes() -> None:
    project_id = os.getenv("MOSS_PROJECT_ID")
    project_key = os.getenv("MOSS_PROJECT_KEY")
    knowledge_index = os.getenv("MOSS_INDEX_NAME", DEFAULT_KNOWLEDGE_INDEX)
    memory_index = os.getenv("MOSS_MEMORY_INDEX_NAME", DEFAULT_MEMORY_INDEX)
    events_index = os.getenv("MOSS_EVENTS_INDEX_NAME", DEFAULT_EVENTS_INDEX)
    model_id = os.getenv("MOSS_MODEL_ID", DEFAULT_MODEL_ID)

    missing = [
        name
        for name, value in {
            "MOSS_PROJECT_ID": project_id,
            "MOSS_PROJECT_KEY": project_key,
        }.items()
        if not value
    ]
    if missing:
        raise OSError(
            "Missing required Moss environment variables: "
            + ", ".join(missing)
            + f". Set them in {ENV_PATH} before running this script."
        )

    assert project_id is not None
    assert project_key is not None

    knowledge_docs = _load_knowledge_documents()
    memory_docs = _memory_seed_documents()
    events_docs = _events_seed_documents()

    client = MossClient(project_id, project_key)

    # Find what already exists so we can skip rebuilds and avoid Moss's
    # per-index BUILD_IN_PROGRESS 409 errors.
    existing_names: set[str] = set()
    try:
        listed = await client.list_indexes()
        for entry in listed or []:
            name = getattr(entry, "name", None) or getattr(entry, "index_name", None)
            if name:
                existing_names.add(str(name))
        print(f"Existing Moss indexes: {sorted(existing_names) or '(none)'}")
    except Exception as e:
        print(f"Could not list existing indexes ({e}); will attempt create anyway.")

    async def _ensure(label: str, index_name: str, docs: list[DocumentInfo]) -> None:
        """Idempotently ensure an index exists.

        - If the index already exists → just `add_docs` to upsert any new
          content. add_docs is the lightweight "warm" path that doesn't
          conflict with prior builds.
        - If it doesn't exist → create_index. On a transient 409 (lock from
          a prior build), assume the in-flight build is the one we want.
        """
        if index_name in existing_names:
            print(
                f"Index '{index_name}' ({label}) already exists. "
                f"Upserting {len(docs)} doc(s) via add_docs…"
            )
            try:
                await client.add_docs(index_name, docs)
                print("  done (upsert)")
            except Exception as e:
                msg = str(e)
                if "BUILD_IN_PROGRESS" in msg or "409" in msg:
                    print(
                        f"  ⚠ Moss is mid-build for '{index_name}'. "
                        f"Skipping upsert — existing content is preserved."
                    )
                    return
                raise
            return

        print(
            f"Creating Moss {label} index '{index_name}' with "
            f"{len(docs)} doc(s) using model '{model_id}'..."
        )
        try:
            result = await client.create_index(index_name, docs, model_id)
            print(
                f"  done (job: {result.job_id}, index: {result.index_name}, "
                f"docs: {result.doc_count})"
            )
        except Exception as e:
            msg = str(e)
            if "BUILD_IN_PROGRESS" in msg or "409" in msg:
                print(
                    f"  ⚠ Build lock on '{index_name}'. Assuming the in-flight "
                    f"build is the current one and moving on."
                )
                return
            raise

    await _ensure("knowledge", knowledge_index, knowledge_docs)
    await _ensure("memory", memory_index, memory_docs)
    await _ensure("events", events_index, events_docs)

    print("All three Moss indexes created: knowledge, memory, events.")


if __name__ == "__main__":
    asyncio.run(build_indexes())
