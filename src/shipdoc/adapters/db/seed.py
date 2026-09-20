"""M17e — load the corpus into the database. Phase 13 B3.

IDEMPOTENT BY CONSTRUCTION, not by a flag. Every write here is keyed on the natural
key — `email_id` for emails, `(email_id, filename)` for attachments — so running the
seed twice updates in place and inserts nothing new. B3's gate is exactly that: run
it twice, assert the row counts are unchanged.

That property is not a nicety. A seed that duplicates on re-run is a seed nobody
dares to run in production, which means the one environment that matters ends up
hand-loaded.

ATTACHMENT BYTES GO TO BLOB STORAGE, not to a column. When Azure Blob Storage is not
configured the metadata (name, size, sha256, detected type) is still recorded and the
upload is skipped — so a developer with a database and no storage account gets a
working, inspectable dataset rather than an error.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

CONTENT_TYPES = {
    ".txt": "text/plain",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}


def _role_of(filename: str) -> str:
    """SI | BL | UNKNOWN, from the corpus filename convention.

    Deliberately NOT the router's logic: this is metadata recorded at ingest time,
    and the authoritative decision is made later by `route/` and `confirm_doc_type`
    against the document CONTENT. Storing a guess here that disagreed with the
    pipeline would be worse than storing nothing.
    """
    stem = Path(filename).stem.upper()
    if stem.endswith("_SI"):
        return "SI"
    if stem.endswith("_BL"):
        return "BL"
    return "UNKNOWN"


class BlobUploader:
    """Azure Blob Storage, or a no-op when it is not configured.

    SAS URLs, never public blobs — a container with public read on it is a shipping
    customer's commercial documents on the open internet.
    """

    def __init__(self, conn: str | None = None, container: str | None = None):
        self.conn = conn or os.environ.get("AZURE_STORAGE_CONNECTION_STRING") or ""
        self.container = container or os.environ.get("AZURE_BLOB_CONTAINER") \
            or "shipdoc-attachments"
        self._client = None
        if not self.conn:
            return
        try:
            from azure.storage.blob import BlobServiceClient
            svc = BlobServiceClient.from_connection_string(self.conn)
            try:
                svc.create_container(self.container)
            except Exception:
                pass                      # already exists: fine
            self._client = svc
        except ImportError:
            self._client = None           # pip install -e ".[blob]"

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def upload(self, email_id: str, filename: str, data: bytes) -> str | None:
        """Returns the blob URL, or None when storage is not configured.

        The URL alone grants no access: the container is private, and the API issues
        a short-lived SAS token when a reviewer actually opens a document.
        """
        if self._client is None:
            return None
        name = f"{email_id}/{filename}"
        blob = self._client.get_blob_client(self.container, name)
        blob.upload_blob(data, overwrite=True)      # overwrite => idempotent
        return blob.url


def seed_corpus(repo, source: str = "dataset", *, uploader: BlobUploader | None = None,
                verbose: bool = True) -> dict:
    """Load emails and attachment metadata. Returns counts. Safe to re-run."""
    from shipdoc.ingest.loader_port import LoaderInbox

    inbox = LoaderInbox(source)
    uploader = uploader if uploader is not None else BlobUploader()
    emails = list(inbox.emails())

    n_att = 0
    with repo.session() as s, s.begin():
        for e in emails:
            repo.upsert_email(
                s, e["email_id"],
                subject=str(e.get("subject") or ""),
                body=str(e.get("body") or ""),
                source="corpus",
            )
        s.flush()
        for e in emails:
            for path in (e.get("attachments") or ()):
                try:
                    data = inbox.read_bytes(path)
                except Exception:          # a corpus file we cannot read is still
                    data = b""             # a fact worth recording
                filename = Path(path).name
                url = uploader.upload(e["email_id"], filename, data) if data else None
                repo.upsert_attachment(
                    s, e["email_id"], filename,
                    sha256=hashlib.sha256(data).hexdigest(),
                    size_bytes=len(data),
                    content_type=CONTENT_TYPES.get(Path(filename).suffix.lower()),
                    blob_url=url,
                    detected_type=_role_of(filename),
                )
                n_att += 1

    counts = repo.counts()
    if verbose:
        print(f"seeded {len(emails)} emails, {n_att} attachments")
        print(f"  emails={counts['emails']} attachments={counts['attachments']}")
        print(f"  blob storage: {'enabled' if uploader.enabled else 'not configured '
                                 '(metadata recorded, upload skipped)'}")
    return counts
