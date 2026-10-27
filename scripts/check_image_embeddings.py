"""Check how EmbeddingGemma 2 scores image evidence on this machine (standard library only).

Run with Ollama and the backend up (docker compose up, or uvicorn on :8000):

    python3 scripts/check_image_embeddings.py

1. Asks Ollama directly whether it reads images: two different photos should give different vectors, and
   neither should equal the empty-text vector.
2. Matches each sample photo against the dispute queue through the backend and prints the raw cosine per
   facet, the queue median, and the resulting score. The Northwind photo should win txn_51be08d4; the taxi
   photo should match nothing. If not, tune IMAGE_MARGIN in backend/app/services/matching.py.
"""

import base64
import json
import os
import urllib.request

OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")
BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
MODEL = os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma-2")
PHOTOS = ["northwind-photo", "taxi-photo"]


def call(url, payload=None, form=None):
    data, headers = None, {}
    if payload is not None:
        data, headers = json.dumps(payload).encode(), {"Content-Type": "application/json"}
    elif form is not None:
        boundary = "----check"
        data = "".join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'
                       for k, v in form.items()).encode() + f"--{boundary}--\r\n".encode()
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=300) as r:
        body = r.read()
    return body if payload is None and form is None else json.loads(body)


def cos(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    return dot / ((sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5))


def main():
    print(f"Ollama {OLLAMA} · model {MODEL}")
    try:
        print("capabilities:", call(f"{OLLAMA}/api/show", {"model": MODEL}).get("capabilities"))
    except Exception as exc:  # noqa: BLE001
        print("could not read /api/show:", exc)

    images = {p: base64.b64encode(call(f"{BACKEND}/api/disputes/samples/{p}")).decode() for p in PHOTOS}
    inputs = [{"text": "", "image": images[p]} for p in PHOTOS] + [""]
    a, b, blank = call(f"{OLLAMA}/api/embed", {"model": MODEL, "input": inputs})["embeddings"]
    print(f"\ncos(photo A, photo B)    = {cos(a, b):.4f}   (well below 1.0 = images are read)")
    print(f"cos(photo A, empty text) = {cos(a, blank):.4f}   (near 1.0 = image ignored)")

    queue = json.loads(call(f"{BACKEND}/api/disputes/transactions"))["transactions"]
    txns = {t["id"]: t["merchant_descriptor"] for t in queue}
    for photo in PHOTOS:
        ev = call(f"{BACKEND}/api/disputes/evidence", form={"sample_id": photo})
        print(f"\n{photo}: matched -> {ev['matched_transaction_id']}")
        print(f"  {'transaction':28} {'score':>6}  raw cosine per facet (median across queue)")
        for row in ev["ranking"]:
            m = ev["matches"][row["transaction_id"]]
            cells = "  ".join(f"{f[:4]} {c[0]:.3f} ({b:.3f})"
                              for f, c, b in zip(m["facets"], m["matrix"], m.get("image_baseline", [])))
            print(f"  {txns[row['transaction_id']][:28]:28} {row['score']:6.2f}  {cells}")


if __name__ == "__main__":
    main()
